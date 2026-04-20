"""Agent-SDK-backed tenant runner with per-checkpoint synthetic tools."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from landlord.contract import Checkpoint, Contract


CHECKPOINT_TOOL_PREFIX = "emit_checkpoint__"


def sanitize_tool_name(name: str) -> str:
    """Coerce an arbitrary checkpoint name into a valid tool name."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def checkpoint_tool_name(cp: Checkpoint) -> str:
    return f"{CHECKPOINT_TOOL_PREFIX}{sanitize_tool_name(cp.name)}"


def build_system_prompt(
    contract: Contract,
    shared_context: str | None,
    retry_context: str | None,
) -> str:
    parts = [
        f"You are a {contract.role}.",
        f"Objective: {contract.objective}",
    ]
    if contract.checkpoints:
        cp_lines = []
        for cp in contract.checkpoints:
            cp_lines.append(
                f"- {cp.name}: call tool `{checkpoint_tool_name(cp)}` when {cp.description}"
            )
        parts.append(
            "Checkpoints - each has a dedicated tool; call it with the required fields "
            "when you reach that checkpoint:\n" + "\n".join(cp_lines)
        )
    parts.append(
        "You also have filesystem and bash tools, sandboxed to your working directory. "
        "Write files, read files, run commands freely. The checkpoint tools are how you "
        "declare structured results back to the orchestrator."
    )
    if shared_context:
        parts.append(f"Context from dependencies:\n{shared_context}")
    if retry_context:
        parts.append(f"Retry context - previous attempt failed:\n{retry_context}")
    return "\n\n".join(parts)


CheckpointHandler = Callable[[str, dict[str, Any]], Awaitable["CheckpointVerdict"]]


@dataclass
class CheckpointVerdict:
    passed: bool
    reason: str


@dataclass
class TenantResult:
    # "complete" when the SDK session returned normally; "evicted" when
    # the task was cancelled mid-session.
    status: str
    # Populated only for status="evicted"; e.g., "cancelled".
    reason: str | None = None
    # Args of the most recent *passing* checkpoint call, or None if no
    # checkpoint passed this attempt. On a multi-checkpoint tenant this
    # is last-pass-wins globally (not per-checkpoint).
    last_output: dict | None = None


class TenantRunner:
    """Runs a single tenant SDK session.

    `sdk_session_factory` is a callable that receives (system_prompt, checkpoint_tool_defs,
    work_dir, model) and returns an object with async `run(sub_prompt, on_checkpoint)` - an
    injection seam so tests can substitute a fake for the real Claude Agent SDK session.
    """

    def __init__(
        self,
        contract: Contract,
        work_dir: Path,
        checkpoint_handler: CheckpointHandler,
        sdk_session_factory: Callable[..., Any],
        model: str,
        shared_context: str | None = None,
        retry_context: str | None = None,
    ) -> None:
        self._contract = contract
        self._work_dir = work_dir
        self._on_checkpoint = checkpoint_handler
        self._sdk_factory = sdk_session_factory
        self._model = model
        self._shared_context = shared_context
        self._retry_context = retry_context

    def build_checkpoint_tool_defs(self) -> list[dict[str, Any]]:
        defs = []
        for cp in self._contract.checkpoints:
            schema = cp.schema if cp.schema.get("type") == "object" else {
                "type": "object",
                "properties": {"result": cp.schema},
                "required": ["result"],
            }
            defs.append({
                "name": checkpoint_tool_name(cp),
                "description": (
                    f"Declare checkpoint '{cp.name}' reached: {cp.description}. "
                    "Call this with the required fields to record your output."
                ),
                "input_schema": schema,
            })
        return defs

    async def run(self) -> TenantResult:
        """Run the tenant's SDK session and return the final result.

        Returns:
            TenantResult with status="complete" when the session ends
            normally, or status="evicted" / reason="cancelled" when the
            asyncio task wrapping this coroutine is cancelled.

        Raises:
            Any exception from the injected sdk_session_factory, the
            underlying SDK session's run(), or the supplied checkpoint
            handler will propagate unchanged. asyncio.CancelledError is
            the only exception this method catches and converts into a
            TenantResult. All others (e.g., the validator's RuntimeError
            when the judge model refuses the forced tool) are the
            caller's responsibility - the orchestrator uses them to
            distinguish infrastructure failures from contract failures.
        """
        system_prompt = build_system_prompt(
            contract=self._contract,
            shared_context=self._shared_context,
            retry_context=self._retry_context,
        )
        tool_defs = self.build_checkpoint_tool_defs()
        session = self._sdk_factory(
            system_prompt=system_prompt,
            checkpoint_tools=tool_defs,
            work_dir=self._work_dir,
            model=self._model,
        )

        last_output: dict | None = None

        async def on_checkpoint_tool_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            nonlocal last_output
            if not tool_name.startswith(CHECKPOINT_TOOL_PREFIX):
                return {"ok": False, "error": f"Unknown tool {tool_name}"}
            sanitized = tool_name[len(CHECKPOINT_TOOL_PREFIX):]
            cp_name = next(
                (cp.name for cp in self._contract.checkpoints if sanitize_tool_name(cp.name) == sanitized),
                sanitized,
            )
            verdict = await self._on_checkpoint(cp_name, args)
            if verdict.passed:
                last_output = args
                return {"ok": True, "message": f"Checkpoint '{cp_name}' passed"}
            return {
                "ok": False,
                "message": f"Checkpoint '{cp_name}' failed: {verdict.reason}. Revise your work and try again.",
            }

        try:
            await session.run(
                sub_prompt=self._contract.sub_prompt,
                on_checkpoint=on_checkpoint_tool_call,
            )
        except asyncio.CancelledError:
            return TenantResult(status="evicted", reason="cancelled", last_output=last_output)

        return TenantResult(status="complete", last_output=last_output)
