"""Legacy sandboxed tool implementations for the old tenant runtime."""

from landlord.legacy.tools.base import Tool, ToolResult
from landlord.legacy.tools.file_write import FileWriteTool
from landlord.legacy.tools.file_read import FileReadTool
from landlord.legacy.tools.shell_exec import ShellExecTool
from landlord.legacy.tools.web_fetch import WebFetchTool
from landlord.legacy.tools.web_search import WebSearchTool

from pathlib import Path


def get_all_tools(base_dir: Path) -> dict[str, Tool]:
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
