"""MCP server exposing Landlord orchestration as five async tools."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field

from landlord.agent_sdk_client import AgentSDKClient
from landlord.contract import Contract
from landlord.jobs import Job, JobRegistry
from landlord.orchestrator import (
    DependencyCycleError,
    Landlord,
    OrchestratorConfig,
    resolve_launch_order,
)
from landlord.validator import Validator


class LandlordServer:
    """Holds the shared state and implements the five MCP tool handlers."""

    def __init__(
        self,
        config: OrchestratorConfig,
        landlord: Landlord,
        default_output_dir: Path,
        registry: JobRegistry | None = None,
    ) -> None:
        self._config = config
        self._landlord = landlord
        self._registry = (
            registry
            if registry is not None
            else getattr(landlord, "_registry", None) or JobRegistry()
        )
        self._default_output_dir = default_output_dir

    def _resolve_output_dir(self, output_dir: str | None) -> Path:
        if output_dir is None:
            return self._default_output_dir
        p = Path(output_dir)
        return p if p.is_absolute() else (Path.cwd() / p).resolve()

    async def start_orchestration(
        self,
        prompt: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        resolved_dir = self._resolve_output_dir(output_dir)
        resolved_dir.mkdir(parents=True, exist_ok=True)
        plan = await self._landlord.decompose(prompt)
        job = await self._registry.create_job(prompt=prompt, plan=plan, output_dir=resolved_dir)
        job.emit_event(
            "job_created",
            prompt=prompt,
            plan=[{"role": c.role, "depends_on": list(c.depends_on)} for c in plan],
        )
        return {
            "job_id": job.job_id,
            "status": job.status,
            "plan": [c.model_dump() for c in job.plan],
            "output_dir": str(job.output_dir),
            "watch_command": f"landlord-watch {job.job_id} --output-dir {str(resolved_dir)!r}",
        }

    async def approve_plan(
        self,
        job_id: str,
        edits: list[dict] | None = None,
    ) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status != "awaiting_approval":
            raise ValueError(f"Job {job_id} is not awaiting approval (status={job.status})")

        if edits is not None:
            try:
                new_plan = [Contract(**raw) for raw in edits]
            except Exception as e:
                raise ValueError(f"Invalid edited plan: {e}") from e
            try:
                resolve_launch_order(new_plan)
            except DependencyCycleError as e:
                raise ValueError(f"Edited plan has a dependency cycle: {e}") from e
            job = await self._registry.replace_plan(job_id, new_plan)

        await self._registry.transition(job_id, "running")
        job.emit_event(
            "plan_approved",
            edited=edits is not None,
            plan=[{"role": c.role, "depends_on": list(c.depends_on)} for c in job.plan],
        )
        await self._landlord.launch(job)
        asyncio.create_task(self._landlord.wait_until_done(job))
        return {"job_id": job_id, "status": "running"}

    async def get_status(self, job_id: str) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        return {
            "job_id": job.job_id,
            "status": job.status,
            "plan": [c.model_dump() for c in job.plan],
            "tenants": [t.to_dict() for t in job.tenants.values()],
            "output_dir": str(job.output_dir),
        }

    async def get_artifacts(self, job_id: str) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status not in ("complete", "partial", "cancelled"):
            raise ValueError(
                f"Artifacts not available for job {job_id} (status={job.status}); "
                f"valid statuses: complete, partial, cancelled"
            )
        files: dict[str, list[str]] = {}
        for tenant_state in job.tenants.values():
            role = tenant_state.contract.role
            tenant_dir = job.output_dir / tenant_state.contract.tenant_id
            if tenant_dir.exists():
                files[role] = sorted(
                    str(p.relative_to(job.output_dir)).replace("\\", "/")
                    for p in tenant_dir.rglob("*") if p.is_file()
                )
            else:
                files[role] = []
        return {
            "job_id": job.job_id,
            "status": job.status,
            "artifacts": dict(job.artifacts),
            "files": files,
        }

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status not in ("awaiting_approval", "running"):
            raise ValueError(f"Cannot cancel job {job_id} (status={job.status})")
        for tenant_state in job.tenants.values():
            if tenant_state.task is not None and not tenant_state.task.done():
                tenant_state.task.cancel()
        await self._registry.transition(job_id, "cancelled")
        job.emit_event("job_cancelled")
        return {"job_id": job_id, "status": "cancelled"}


def _build_sdk_session_factory() -> Any:
    """Build the production SDK session factory.

    Importing claude_agent_sdk is deferred so the test suite can run without it
    installed. The factory adapter maps TenantRunner's interface to the real SDK.
    """
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        PermissionResultAllow,
        PermissionResultDeny,
        create_sdk_mcp_server,
        tool,
    )

    def factory(system_prompt, checkpoint_tools, work_dir, model, role=None, permission_callback=None):
        return _SDKSessionAdapter(
            system_prompt=system_prompt,
            checkpoint_tools=checkpoint_tools,
            work_dir=work_dir,
            model=model,
            role=role,
            permission_callback=permission_callback,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ClaudeSDKClient=ClaudeSDKClient,
            create_sdk_mcp_server=create_sdk_mcp_server,
            tool=tool,
            PermissionResultAllow=PermissionResultAllow,
            PermissionResultDeny=PermissionResultDeny,
        )
    return factory


class _SDKSessionAdapter:
    """Adapts ClaudeSDKClient to TenantRunner's `run(sub_prompt, on_checkpoint)` protocol.

    Registers each checkpoint tool as an in-process SDK MCP tool whose handler calls
    the `on_checkpoint` callback supplied by TenantRunner.
    """
    def __init__(
        self,
        system_prompt,
        checkpoint_tools,
        work_dir,
        model,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        create_sdk_mcp_server,
        tool,
        role=None,
        permission_callback=None,
        PermissionResultAllow=None,
        PermissionResultDeny=None,
    ):
        self._system_prompt = system_prompt
        self._checkpoint_tools = checkpoint_tools
        self._work_dir = work_dir
        self._model = model
        self._role = role or "tenant"
        self._permission_callback = permission_callback
        self._ClaudeAgentOptions = ClaudeAgentOptions
        self._ClaudeSDKClient = ClaudeSDKClient
        self._create_sdk_mcp_server = create_sdk_mcp_server
        self._tool = tool
        self._PermissionResultAllow = PermissionResultAllow
        self._PermissionResultDeny = PermissionResultDeny

    async def run(self, sub_prompt, on_checkpoint):
        sdk_tools = []
        for t in self._checkpoint_tools:
            tool_name = t["name"]
            input_schema = t["input_schema"]

            async def handler(args, _tool_name=tool_name):
                result = await on_checkpoint(_tool_name, args)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            sdk_tools.append(self._tool(tool_name, t["description"], input_schema)(handler))

        mcp_server = self._create_sdk_mcp_server(
            name="landlord_checkpoints", version="1.0.0", tools=sdk_tools
        )
        # Tenants inherit the user's ~/.claude/ config (skills, CLAUDE.md, hooks,
        # user memory, personal MCP servers). `skills="all"` makes every user-
        # level skill available to the tenant via the Skill tool.
        #
        # Permission model: two paths.
        #
        # 1. Interactive (permission_callback supplied) — every tool call goes
        #    through can_use_tool, which forwards the decision to the calling
        #    Claude session via Context.elicit. The user sees a prompt with the
        #    tool name + args and clicks allow/deny. Used by the streaming MCP
        #    tools (run_orchestration, approve_plan).
        # 2. Autonomous (no permission_callback) — bypassPermissions skips the
        #    prompt layer entirely so the tenant doesn't deadlock waiting for a
        #    human that isn't there. Used by start_orchestration's fire-and-
        #    forget path and by direct Python API callers.
        #
        # `add_dirs` grants read access to the process's cwd at launch time
        # (typically the user's project root when Claude Code spawns the MCP
        # server via stdio). Without this, tenants can only see their own
        # sandboxed subdirectory and cannot read the calling repo's code.
        common_options = dict(
            system_prompt=self._system_prompt,
            cwd=str(self._work_dir),
            model=self._model,
            mcp_servers={"checkpoints": mcp_server},
            setting_sources=["user"],
            skills="all",
            add_dirs=[str(Path.cwd())],
        )
        if self._permission_callback is not None:
            assert self._PermissionResultAllow is not None
            assert self._PermissionResultDeny is not None
            cb = self._permission_callback
            role = self._role
            allow_cls = self._PermissionResultAllow
            deny_cls = self._PermissionResultDeny

            async def can_use_tool(tool_name, tool_input, _ctx):
                # Forward to the orchestrator-supplied callback. On any error
                # (e.g., the calling client doesn't support elicitation, or the
                # call times out), default to allow so the tenant doesn't
                # deadlock — matches the autonomous-mode behaviour.
                try:
                    allowed = await cb(role, tool_name, tool_input)
                except Exception:
                    allowed = True
                if allowed:
                    return allow_cls(updated_input=tool_input)
                return deny_cls(message=f"User denied {tool_name} for tenant '{role}'")

            options = self._ClaudeAgentOptions(
                **common_options,
                can_use_tool=can_use_tool,
            )
        else:
            options = self._ClaudeAgentOptions(
                **common_options,
                permission_mode="bypassPermissions",
            )
        log_path = Path(self._work_dir) / "session.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            log.write(f"=== tenant session start: model={self._model} ===\n")
            log.write(f"=== sub_prompt ===\n{sub_prompt}\n=== end sub_prompt ===\n")
            async with self._ClaudeSDKClient(options=options) as client:
                await client.query(sub_prompt)
                async for message in client.receive_response():
                    log.write(_format_message_for_log(message))
                    log.write("\n")
            log.write("=== tenant session end ===\n")


def _format_message_for_log(message: Any) -> str:
    """Render an SDK message as a single tail-friendly block.

    Tries to unpack the common message types (assistant text, thinking, tool
    use/result, rate limit info) and falls back to repr() for unknown shapes.
    """
    kind = type(message).__name__
    content = getattr(message, "content", None)
    if content is None:
        return f"[{kind}] {message!r}"
    parts: list[str] = [f"[{kind}]"]
    if isinstance(content, list):
        for block in content:
            block_kind = type(block).__name__
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(f"  <{block_kind}> {text}")
                continue
            tool_name = getattr(block, "name", None)
            tool_input = getattr(block, "input", None)
            if tool_name is not None:
                parts.append(f"  <{block_kind}> tool={tool_name} input={tool_input!r}")
                continue
            result = getattr(block, "content", None)
            if result is not None:
                parts.append(f"  <{block_kind}> result={result!r}")
                continue
            parts.append(f"  <{block_kind}> {block!r}")
    else:
        parts.append(f"  {content!r}")
    return "\n".join(parts)


def build_default_server() -> LandlordServer:
    """Wire a production LandlordServer from environment configuration."""
    config = OrchestratorConfig.from_env()
    default_output = Path(os.environ.get("LANDLORD_OUTPUT_DIR", "./landlord-output")).resolve()
    default_output.mkdir(parents=True, exist_ok=True)
    client = AgentSDKClient(model=config.landlord_model)
    validator = Validator(client=client)
    registry = JobRegistry()
    landlord = Landlord(
        config=config,
        registry=registry,
        client=client,
        validator=validator,
        sdk_session_factory=_build_sdk_session_factory(),
    )
    return LandlordServer(
        config=config,
        landlord=landlord,
        default_output_dir=default_output,
        registry=registry,
    )


_TERMINAL_JOB_STATUSES = ("complete", "partial", "cancelled")


class _PermissionDecision(BaseModel):
    """Schema for the elicitation prompt that asks the user to allow/deny a tenant tool call."""

    allow: bool = Field(
        description=(
            "True to allow the tenant to use the tool with the proposed input. "
            "False to deny — the tenant will receive an error and decide how to proceed."
        )
    )


def _build_permission_callback(ctx: Any):
    """Construct a PermissionCallback that forwards tenant tool decisions to
    the calling Claude session via Context.elicit. Falls back to allow if the
    client doesn't support elicitation or any other error occurs."""
    async def callback(role: str, tool_name: str, tool_input: dict[str, Any]) -> bool:
        # Truncate the input preview so the prompt stays readable.
        try:
            input_str = json.dumps(tool_input, default=str)
        except Exception:
            input_str = repr(tool_input)
        if len(input_str) > 400:
            input_str = input_str[:397] + "..."

        message = (
            f"Tenant '{role}' wants to use tool '{tool_name}'.\n\n"
            f"Input: {input_str}\n\n"
            f"Allow this tool call?"
        )
        try:
            result = await ctx.elicit(message=message, schema=_PermissionDecision)
            data = getattr(result, "data", None)
            action = getattr(result, "action", None)
            if action == "accept" and data is not None:
                return bool(getattr(data, "allow", True))
            # Decline / cancel from the user is treated as a deny.
            if action in ("decline", "cancel"):
                return False
            # Unknown shape — default allow so the orchestration doesn't deadlock.
            return True
        except Exception:
            return True
    return callback


def _format_event_message(event: dict[str, Any]) -> str:
    """One-line human-readable summary for a progress notification."""
    t = event.get("type", "?")
    role = event.get("role")
    cp = event.get("checkpoint")
    reason = event.get("reason", "")
    retry = event.get("retry_count")
    if t == "job_created":
        n = len(event.get("plan", []))
        return f"plan decomposed into {n} tenant{'s' if n != 1 else ''}"
    if t == "plan_approved":
        return "plan approved, launching tenants"
    if t == "tenant_started":
        suffix = f" (retry {retry})" if retry else ""
        return f"[{role}] started{suffix}"
    if t == "checkpoint_passed":
        return f"[{role}] ✓ {cp}"
    if t == "checkpoint_failed":
        return f"[{role}] ✗ {cp} — {reason[:80]}"
    if t == "tenant_retrying":
        return f"[{role}] retrying (#{retry})"
    if t == "tenant_evicted":
        return f"[{role}] evicted — {reason[:80]}"
    if t == "tenant_escalated":
        return f"[{role}] escalated after {retry} retries"
    if t == "tenant_complete":
        return f"[{role}] complete"
    if t.startswith("job_"):
        return f"job {t[4:]}"
    return t


async def _stream_until_done(
    server: LandlordServer,
    ctx: Any,
    job_id: str,
    started_event_count: int = 0,
    poll_interval: float = 0.5,
) -> dict[str, Any]:
    """Poll events.jsonl and forward each new event as a progress notification.

    Returns the final get_artifacts response once the job reaches a terminal
    status. ctx is a FastMCP Context with report_progress(); if the client
    didn't request progress notifications the calls are effectively no-ops
    so this is safe either way.
    """
    from landlord.watch import load_events

    seen = started_event_count
    progress = float(started_event_count)
    while True:
        job = await server._registry.get(job_id)
        if job is None:
            raise ValueError(f"Job vanished mid-run: {job_id}")
        events = load_events(job.output_dir)
        for event in events[seen:]:
            message = _format_event_message(event)
            progress += 1
            try:
                await ctx.report_progress(progress=progress, total=None, message=message)
            except Exception:
                pass  # client may not support progress; keep streaming events to disk
        seen = len(events)
        if job.status in _TERMINAL_JOB_STATUSES:
            break
        await asyncio.sleep(poll_interval)

    # Reuse the standard artifacts accessor so the response shape matches.
    try:
        return await server.get_artifacts(job_id=job_id)
    except ValueError:
        # get_artifacts refuses on non-terminal statuses, but we just checked.
        # Fall back to the status response.
        return await server.get_status(job_id=job_id)


def main() -> None:
    """Entry point for the `landlord-mcp` console script. Runs the stdio server."""
    from mcp.server.fastmcp import FastMCP

    server = build_default_server()
    mcp = FastMCP("landlord")

    @mcp.tool()
    async def run_orchestration(
        ctx: Context,
        prompt: str,
        output_dir: str | None = None,
    ) -> dict:
        """Decompose, approve, run, and stream live progress — all in one call.

        This is the recommended entry point for most use cases. The tool call
        stays open for the full orchestration; progress notifications stream
        plan decomposition, per-tenant starts, checkpoint pass/fail events,
        retries, and completion directly into Claude Code's tool bubble.
        Returns the final artifacts once the job reaches a terminal status.

        Use the lower-level tools (start_orchestration, approve_plan, etc.)
        if you need to inspect the plan before approving or drive the
        orchestration step-by-step.
        """
        await ctx.report_progress(progress=0, total=None, message="decomposing prompt...")
        started = await server.start_orchestration(prompt=prompt, output_dir=output_dir)
        plan_roles = [c["role"] for c in started["plan"]]
        await ctx.report_progress(
            progress=1, total=None,
            message=f"plan: {', '.join(plan_roles)}",
        )
        # Approve manually so we can pass a permission callback into launch.
        job = await server._registry.get(started["job_id"])
        await server._registry.transition(started["job_id"], "running")
        job.emit_event(
            "plan_approved",
            edited=False,
            plan=[{"role": c.role, "depends_on": list(c.depends_on)} for c in job.plan],
        )
        permission_cb = _build_permission_callback(ctx)
        await server._landlord.launch(job, permission_callback=permission_cb)
        asyncio.create_task(server._landlord.wait_until_done(job))
        result = await _stream_until_done(server, ctx, started["job_id"], started_event_count=2)
        return {
            "job_id": started["job_id"],
            "output_dir": started["output_dir"],
            **result,
        }

    @mcp.tool()
    async def start_orchestration(prompt: str, output_dir: str | None = None) -> dict:
        """Decompose the prompt into a plan and return job_id + plan awaiting approval.

        Use run_orchestration instead unless you want to inspect or edit the
        plan before tenants launch.
        """
        return await server.start_orchestration(prompt=prompt, output_dir=output_dir)

    @mcp.tool()
    async def approve_plan(
        ctx: Context,
        job_id: str,
        edits: list[dict] | None = None,
    ) -> dict:
        """Approve (or replace via edits) the plan for job_id, then stream progress until done.

        Tenant tool calls are forwarded to you via Context.elicit — you'll see
        an "allow / deny" prompt for each Write/Bash/etc the tenant attempts.
        Returns the final artifacts once the job reaches a terminal status.
        """
        # Replicate server.approve_plan's preconditions/edits handling but
        # plumb a permission callback through launch so we can route tool
        # decisions back to the user.
        job = await server._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status != "awaiting_approval":
            raise ValueError(f"Job {job_id} is not awaiting approval (status={job.status})")
        if edits is not None:
            try:
                new_plan = [Contract(**raw) for raw in edits]
            except Exception as e:
                raise ValueError(f"Invalid edited plan: {e}") from e
            try:
                resolve_launch_order(new_plan)
            except DependencyCycleError as e:
                raise ValueError(f"Edited plan has a dependency cycle: {e}") from e
            job = await server._registry.replace_plan(job_id, new_plan)
        await server._registry.transition(job_id, "running")
        job.emit_event(
            "plan_approved",
            edited=edits is not None,
            plan=[{"role": c.role, "depends_on": list(c.depends_on)} for c in job.plan],
        )
        permission_cb = _build_permission_callback(ctx)
        await server._landlord.launch(job, permission_callback=permission_cb)
        asyncio.create_task(server._landlord.wait_until_done(job))
        return await _stream_until_done(server, ctx, job_id)

    @mcp.tool()
    async def get_status(job_id: str) -> dict:
        """Return current status, plan, and per-tenant states for job_id."""
        return await server.get_status(job_id=job_id)

    @mcp.tool()
    async def get_artifacts(job_id: str) -> dict:
        """Return final artifacts and file lists; requires job to be done or cancelled."""
        return await server.get_artifacts(job_id=job_id)

    @mcp.tool()
    async def cancel(job_id: str) -> dict:
        """Cancel a running or pending job."""
        return await server.cancel(job_id=job_id)

    mcp.run()


if __name__ == "__main__":
    main()
