"""File read tool for tenant workers."""
from __future__ import annotations

from pathlib import Path

from landlord.tools.base import ToolResult


class FileReadTool:
    """Reads files relative to a sandboxed base directory."""

    name = "file_read"
    description = "Read content from a file path relative to the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path to read"},
        },
        "required": ["path"],
    }

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()

    def _safe_path(self, path: str) -> Path | None:
        """Return resolved path if within base_dir, else None."""
        target = (self._base_dir / path).resolve()
        try:
            target.relative_to(self._base_dir)
        except ValueError:
            return None
        return target

    async def execute(self, **kwargs) -> ToolResult:
        path: str = kwargs["path"]
        target = self._safe_path(path)
        if target is None:
            return ToolResult(success=False, output="", error="Access denied: path traversal")
        if not target.exists():
            return ToolResult(success=False, output="", error=f"File not found: {path}")
        content = target.read_text()
        return ToolResult(success=True, output=content)
