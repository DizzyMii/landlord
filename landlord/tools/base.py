"""Tool protocol and base types for the tenant tool system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    output: str
    error: str | None = None


@runtime_checkable
class Tool(Protocol):
    """Protocol that all tools must satisfy."""

    name: str
    description: str
    parameters: dict

    async def execute(self, **kwargs) -> ToolResult: ...
