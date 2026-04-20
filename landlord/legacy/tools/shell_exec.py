"""Shell execution tool for tenant workers."""
from __future__ import annotations

import asyncio
from pathlib import Path

from landlord.legacy.tools.base import ToolResult


class ShellExecTool:
    """Executes shell commands in the sandboxed base directory."""

    name = "shell_exec"
    description = "Execute a shell command in the working directory."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
        },
        "required": ["command"],
    }

    def __init__(self, base_dir: Path, timeout: int = 30) -> None:
        self._base_dir = base_dir
        self._timeout = timeout

    async def execute(self, **kwargs) -> ToolResult:
        command: str = kwargs["command"]
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._base_dir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {self._timeout}s: timeout",
            )
        output = stdout.decode().strip()
        err_text = stderr.decode().strip()
        if proc.returncode != 0:
            return ToolResult(
                success=False,
                output=output,
                error=f"Command exited with code {proc.returncode}: {err_text}",
            )
        return ToolResult(success=True, output=output, error=err_text or None)
