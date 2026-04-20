"""Agent-SDK-backed client for one-shot forced-tool calls.

Replaces the raw `anthropic` SDK usage (API-key auth) so the orchestrator's
decompose and the validator's judge both route through `claude_agent_sdk.query()`.
That honours CLAUDE_CODE_OAUTH_TOKEN, meaning callers authenticated via
`claude setup-token` run on their Claude Pro/Max subscription rather than
paying per-token API billing.

The public `call_forced_tool(system, messages, tool)` API mirrors the previous
AnthropicClient so Validator and Landlord orchestrator code does not change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    query as default_query,
    tool as sdk_tool,
)


QueryFn = Callable[..., Any]


@dataclass
class UsageStats:
    """Best-effort tracking. The Agent SDK surfaces usage in ResultMessage blocks."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


class AgentSDKClient:
    """Drives claude_agent_sdk.query() for one-shot forced-tool calls.

    Each `call_forced_tool` builds an in-process SDK MCP server exposing exactly
    the forced tool, runs a constrained query, and returns the tool's input args
    (captured by the tool's callback).
    """

    def __init__(
        self,
        model: str,
        query_fn: QueryFn | None = None,
        max_turns: int = 4,
    ) -> None:
        self._model = model
        self._query = query_fn or default_query
        self._max_turns = max_turns
        self.usage = UsageStats()

    @property
    def model(self) -> str:
        return self._model

    async def call_forced_tool(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a one-shot query that is required to call the given tool once.

        Parameters:
            system: The system prompt text.
            messages: A list of {"role": "user", "content": str} entries. Contents
                are concatenated into a single user prompt in order (the SDK's
                query() takes a single prompt string).
            tool: A tool definition dict with keys ``name``, ``description``,
                ``input_schema``.

        Returns:
            The tool's ``input`` dict — whatever the model passed into the tool.

        Raises:
            RuntimeError: If the model never called the forced tool (e.g., a
                safety refusal or a blank response).
        """
        captured: dict[str, Any] = {}

        @sdk_tool(tool["name"], tool["description"], tool["input_schema"])
        async def _capture(args: dict[str, Any]) -> dict[str, Any]:
            captured.update(args)
            return {"content": [{"type": "text", "text": "recorded"}]}

        mcp_server = create_sdk_mcp_server(
            name="forced_tool", version="1.0.0", tools=[_capture]
        )
        qualified_tool = f"mcp__forced_tool__{tool['name']}"

        augmented_system = (
            f"{system}\n\n"
            f"You MUST call the `{tool['name']}` tool exactly once with your answer. "
            f"Do not reply in prose. Do not use any other tool."
        )

        prompt_parts = [m.get("content", "") for m in messages if m.get("role") == "user"]
        prompt = "\n\n".join(prompt_parts)

        options = ClaudeAgentOptions(
            system_prompt=augmented_system,
            mcp_servers={"forced_tool": mcp_server},
            allowed_tools=[qualified_tool],
            model=self._model,
            max_turns=self._max_turns,
            setting_sources=None,
            skills=None,
        )

        last_message: Any = None
        async for message in self._query(prompt=prompt, options=options):
            last_message = message
            self._track(message)

        if not captured:
            raise RuntimeError(
                f"Model did not call forced tool {tool['name']!r}; "
                f"last_message={type(last_message).__name__ if last_message else 'None'}"
            )
        return captured

    def _track(self, message: Any) -> None:
        # Keep this method synchronous — no awaits — so concurrent callers'
        # usage updates remain atomic under asyncio.
        usage = getattr(message, "usage", None)
        if usage is None:
            return
        self.usage.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.usage.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.usage.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
