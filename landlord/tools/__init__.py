"""Tool system for tenant workers."""
from __future__ import annotations

from pathlib import Path

from landlord.tools.base import Tool, ToolResult
from landlord.tools.file_write import FileWriteTool
from landlord.tools.file_read import FileReadTool
from landlord.tools.shell_exec import ShellExecTool
from landlord.tools.web_fetch import WebFetchTool
from landlord.tools.web_search import WebSearchTool


def get_all_tools(base_dir: Path) -> dict[str, Tool]:
    """Create all standard tools for a tenant working in base_dir."""
    tools: list[Tool] = [
        FileWriteTool(base_dir=base_dir),
        FileReadTool(base_dir=base_dir),
        ShellExecTool(base_dir=base_dir),
        WebFetchTool(),
        WebSearchTool(),
    ]
    return {t.name: t for t in tools}


__all__ = [
    "Tool",
    "ToolResult",
    "FileWriteTool",
    "FileReadTool",
    "ShellExecTool",
    "WebFetchTool",
    "WebSearchTool",
    "get_all_tools",
]
