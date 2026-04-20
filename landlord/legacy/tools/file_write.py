"""File write tool for tenant workers."""
from __future__ import annotations

from pathlib import Path

from landlord.legacy.tools.base import ToolResult


class FileWriteTool:
    """Writes files relative to a sandboxed base directory."""

    name = "file_write"
    description = "Write content to a file path relative to the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path to write"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        "required": ["path", "content"],
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
        content: str = kwargs["content"]
        target = self._safe_path(path)
        if target is None:
            return ToolResult(success=False, output="", error="Access denied: path traversal")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return ToolResult(success=True, output=f"Wrote {len(content)} bytes to {path}")
