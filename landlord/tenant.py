"""Tenant worker - an isolated async agent that executes a contract."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from landlord.contract import Checkpoint, Contract
from landlord.event_bus import Event, EventBus
from landlord.llm_client import LLMClient
from landlord.tools.base import Tool

import re

CHECKPOINT_TOOL_PREFIX = "emit_checkpoint__"


def _sanitize_tool_name(name: str) -> str:
    """Sanitize a name for use in an OpenAI tool name (alphanumeric, _, -)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _build_checkpoint_tool(cp: Checkpoint) -> dict:
    """Build a tool definition for a specific checkpoint.

    Each checkpoint gets its own tool so the LLM's structured
    tool-calling is forced to populate the required output fields.
    """
    return {
        "type": "function",
        "function": {
            "name": f"{CHECKPOINT_TOOL_PREFIX}{_sanitize_tool_name(cp.name)}",
            "description": (
                f"Declare that you have reached checkpoint '{cp.name}': {cp.description}. "
                f"You MUST include all required fields in the parameters."
            ),
            "parameters": cp.schema if cp.schema.get("type") == "object" else {
                "type": "object",
                "properties": {"result": cp.schema},
                "required": ["result"],
            },
        },
    }


class Tenant:
    """An isolated async worker that executes a contract."""

    def __init__(
        self,
        contract: Contract,
        llm_client: LLMClient,
        event_bus: EventBus,
        tools: dict[str, Tool],
        work_dir: Path,
        shared_context: str | None = None,
    ) -> None:
        self.contract = contract
        self._llm = llm_client
        self._bus = event_bus
        self._work_dir = work_dir
        self._shared_context = shared_context

        # Filter tools based on contract restrictions
        allowed_names = contract.effective_tools(list(tools.keys()))
        self._tools = {name: tools[name] for name in allowed_names if name in tools}

        # Map sanitized checkpoint tool names back to original checkpoint names
        self._checkpoint_name_map = {
            _sanitize_tool_name(cp.name): cp.name for cp in contract.checkpoints
        }

    def _build_system_message(self) -> str:
        parts = [
            f"You are a {self.contract.role}.",
            f"Objective: {self.contract.objective}",
        ]
        if self.contract.checkpoints:
            cp_lines = []
            for cp in self.contract.checkpoints:
                tool_name = f"{CHECKPOINT_TOOL_PREFIX}{_sanitize_tool_name(cp.name)}"
                cp_lines.append(
                    f"- Call tool '{tool_name}' when: {cp.description}"
                )
            parts.append(
                "Checkpoints to hit (each has its own tool — call the "
                "corresponding tool with the required fields):\n"
                + "\n".join(cp_lines)
            )
        if self._tools:
            tool_desc = "\n".join(f"- {name}" for name in self._tools)
            parts.append(f"Available tools:\n{tool_desc}")
        if self._shared_context:
            parts.append(f"Artifacts from dependencies:\n{self._shared_context}")
        return "\n\n".join(parts)

    def _build_tool_defs(self) -> list[dict]:
        defs = []
        # Add checkpoint-specific tools
        for cp in self.contract.checkpoints:
            defs.append(_build_checkpoint_tool(cp))
        # Add standard tools
        for tool in self._tools.values():
            defs.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return defs

    async def run(self) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_message()},
            {"role": "user", "content": self.contract.sub_prompt},
        ]
        if self.contract.context:
            messages.append({"role": "user", "content": f"Previous attempt context: {self.contract.context}"})

        tool_defs = self._build_tool_defs()

        try:
            while True:
                response = await self._llm.chat_with_tools(messages, tool_defs)
                choice = response.choices[0].message
                messages.append(choice.model_dump())

                if not choice.tool_calls:
                    await self._bus.publish(Event(
                        tenant_id=self.contract.tenant_id,
                        event_type="task_complete",
                        payload={"final_message": choice.content or ""},
                    ))
                    return

                for tool_call in choice.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    if fn_name.startswith(CHECKPOINT_TOOL_PREFIX):
                        sanitized = fn_name[len(CHECKPOINT_TOOL_PREFIX):]
                        cp_name = self._checkpoint_name_map.get(sanitized, sanitized)
                        # The args ARE the output (the schema is the tool params)
                        future: asyncio.Future = asyncio.get_event_loop().create_future()
                        await self._bus.publish(Event(
                            tenant_id=self.contract.tenant_id,
                            event_type="checkpoint_reached",
                            payload={
                                "name": cp_name,
                                "output": fn_args,
                                "future": future,
                            },
                        ))
                        validation_result = await future
                        if not validation_result.passed:
                            return
                        tool_result_content = f"Checkpoint '{cp_name}' validated successfully."
                    elif fn_name in self._tools:
                        result = await self._tools[fn_name].execute(**fn_args)
                        tool_result_content = result.output if result.success else f"Error: {result.error}"
                    else:
                        tool_result_content = f"Error: Unknown tool '{fn_name}'"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result_content,
                    })

        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._bus.publish(Event(
                tenant_id=self.contract.tenant_id,
                event_type="task_failed",
                payload={"error": str(e)},
            ))
