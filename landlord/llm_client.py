"""LLM client wrapper around litellm for provider-agnostic API calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

import litellm


@dataclass
class TokenUsage:
    """Tracks cumulative token usage."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    """Thin wrapper around litellm with token tracking."""

    def __init__(self, model: str) -> None:
        self.model = model
        self._usage = TokenUsage()

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    def _track_usage(self, response) -> None:
        if hasattr(response, "usage") and response.usage:
            self._usage.prompt_tokens += response.usage.prompt_tokens
            self._usage.completion_tokens += response.usage.completion_tokens

    async def chat(self, messages: list[dict]) -> str:
        """Send messages and return the assistant's text response."""
        response = await litellm.acompletion(model=self.model, messages=messages)
        self._track_usage(response)
        return response.choices[0].message.content or ""

    async def chat_with_tools(self, messages: list[dict], tools: list[dict]):
        """Send messages with tool definitions. Returns raw litellm response."""
        response = await litellm.acompletion(
            model=self.model, messages=messages, tools=tools
        )
        self._track_usage(response)
        return response

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream a chat response, yielding text chunks."""
        response = await litellm.acompletion(
            model=self.model, messages=messages, stream=True
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
