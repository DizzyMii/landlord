"""MCP server exposing Landlord orchestration as five async tools."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

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
        return {
            "job_id": job.job_id,
            "status": job.status,
            "plan": [c.model_dump() for c in job.plan],
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
        return {"job_id": job_id, "status": "cancelled"}


def _build_sdk_session_factory() -> Any:
    """Build the production SDK session factory.

    Importing claude_agent_sdk is deferred so the test suite can run without it
    installed. The factory adapter maps TenantRunner's interface to the real SDK.
    """
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        create_sdk_mcp_server,
        tool,
    )

    def factory(system_prompt, checkpoint_tools, work_dir, model):
        return _SDKSessionAdapter(
            system_prompt=system_prompt,
            checkpoint_tools=checkpoint_tools,
            work_dir=work_dir,
            model=model,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ClaudeSDKClient=ClaudeSDKClient,
            create_sdk_mcp_server=create_sdk_mcp_server,
            tool=tool,
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
    ):
        self._system_prompt = system_prompt
        self._checkpoint_tools = checkpoint_tools
        self._work_dir = work_dir
        self._model = model
        self._ClaudeAgentOptions = ClaudeAgentOptions
        self._ClaudeSDKClient = ClaudeSDKClient
        self._create_sdk_mcp_server = create_sdk_mcp_server
        self._tool = tool

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
        # Permission model: an autonomous orchestrator has no human to approve
        # tool-permission prompts, so leaving `permission_mode` at its default
        # value would deadlock on the first Write/Bash call. We bypass the
        # prompt layer entirely. Tenants have unrestricted access to their cwd
        # and to any directory listed in `add_dirs`. The trust boundary is the
        # orchestrator's `output_dir` and the user's project root — if that's
        # unacceptable for a given task, run it with a narrower output_dir.
        #
        # `add_dirs` grants read access to the process's cwd at launch time
        # (typically the user's project root when Claude Code spawns the MCP
        # server via stdio). Without this, tenants can only see their own
        # sandboxed subdirectory and cannot read the calling repo's code.
        options = self._ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            cwd=str(self._work_dir),
            model=self._model,
            mcp_servers={"checkpoints": mcp_server},
            setting_sources=["user"],
            skills="all",
            permission_mode="bypassPermissions",
            add_dirs=[str(Path.cwd())],
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


def main() -> None:
    """Entry point for the `landlord-mcp` console script. Runs the stdio server."""
    from mcp.server.fastmcp import FastMCP

    server = build_default_server()
    mcp = FastMCP("landlord")

    @mcp.tool()
    async def start_orchestration(prompt: str, output_dir: str | None = None) -> dict:
        """Decompose the prompt into a plan and return job_id + plan awaiting approval."""
        return await server.start_orchestration(prompt=prompt, output_dir=output_dir)

    @mcp.tool()
    async def approve_plan(job_id: str, edits: list[dict] | None = None) -> dict:
        """Approve (or replace via edits) the plan for job_id and launch tenants."""
        return await server.approve_plan(job_id=job_id, edits=edits)

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
