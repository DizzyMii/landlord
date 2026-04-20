"""Thin Anthropic SDK wrapper with cache_control, forced tool use, and usage tracking."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic


@dataclass
class CachedBlock:
    """A system-prompt block that may or may not be marked for ephemeral caching."""

    text: str
    cache: bool = False


@dataclass
class UsageStats:
    """Cumulative token usage across all calls made by this client."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def _render_system(blocks: list[CachedBlock]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for block in blocks:
        entry: dict[str, Any] = {"type": "text", "text": block.text}
        if block.cache:
            entry["cache_control"] = {"type": "ephemeral"}
        rendered.append(entry)
    return rendered


class AnthropicClient:
    """Anthropic SDK wrapper with cache_control + forced tool-use helpers."""

    def __init__(self, model: str, api_key: str | None = None, max_tokens: int = 4096) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._sdk = AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.usage = UsageStats()

    @property
    def model(self) -> str:
        return self._model

    def _track(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        if u is None:
            return
        self.usage.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.usage.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.usage.cache_creation_input_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.usage.cache_read_input_tokens += getattr(u, "cache_read_input_tokens", 0) or 0

    async def messages(
        self,
        system: list[CachedBlock],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        """Send a messages call. Returns the raw SDK response."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": _render_system(system),
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        response = await self._sdk.messages.create(**kwargs)
        self._track(response)
        return response

    async def call_forced_tool(
        self,
        system: list[CachedBlock],
        messages: list[dict[str, Any]],
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        """Force the model to call the given tool and return its arguments as a dict.

        `tool` is a single tool definition (with name, description, input_schema).
        Returns the tool's `input` (arguments) dict.
        """
        response = await self.messages(
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        raise RuntimeError(f"Model did not call forced tool {tool['name']}")
