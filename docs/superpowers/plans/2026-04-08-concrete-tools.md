# Concrete Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 5 concrete tools (file_write, file_read, shell_exec, web_fetch, web_search) plus a tool registry in `__init__.py`, with full test coverage.

**Architecture:** Each tool is a standalone class satisfying the `Tool` protocol from `landlord/tools/base.py`. File tools enforce path traversal prevention. Network tools use `httpx.AsyncClient`. The registry wires all tools into a dict keyed by name.

**Tech Stack:** Python 3.11+, asyncio, httpx>=0.27, pytest-asyncio

---

### Task 1: Add httpx dependency and install

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add httpx to dependencies**

In `pyproject.toml`, change the `dependencies` list to include `httpx>=0.27`:

```toml
dependencies = [
    "litellm>=1.40",
    "pydantic>=2.0",
    "typer>=0.12",
    "rich>=13.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Install the updated dependencies**

Run: `pip install -e ".[dev]"`
Expected: Successfully installed httpx (and any sub-dependencies)

- [ ] **Step 3: Verify httpx importable**

Run: `python -c "import httpx; print(httpx.__version__)"`
Expected: prints a version string like `0.27.x`

---

### Task 2: Write all tests for concrete tools

**Files:**
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Append all test classes to `tests/test_tools.py`**

Append the following to the end of `tests/test_tools.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from landlord.tools.file_write import FileWriteTool
from landlord.tools.file_read import FileReadTool
from landlord.tools.shell_exec import ShellExecTool
from landlord.tools.web_fetch import WebFetchTool
from landlord.tools.web_search import WebSearchTool


class TestFileWriteTool:
    async def test_write_file(self, tmp_work_dir):
        tool = FileWriteTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="test.txt", content="hello world")
        assert result.success is True
        assert (tmp_work_dir / "test.txt").read_text() == "hello world"

    async def test_write_creates_subdirectories(self, tmp_work_dir):
        tool = FileWriteTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="sub/dir/test.txt", content="nested")
        assert result.success is True
        assert (tmp_work_dir / "sub" / "dir" / "test.txt").read_text() == "nested"

    async def test_write_rejects_path_traversal(self, tmp_work_dir):
        tool = FileWriteTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="../../../etc/passwd", content="hacked")
        assert result.success is False
        assert "denied" in result.error.lower()


class TestFileReadTool:
    async def test_read_file(self, tmp_work_dir):
        (tmp_work_dir / "test.txt").write_text("hello")
        tool = FileReadTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="test.txt")
        assert result.success is True
        assert result.output == "hello"

    async def test_read_missing_file(self, tmp_work_dir):
        tool = FileReadTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="nonexistent.txt")
        assert result.success is False

    async def test_read_rejects_path_traversal(self, tmp_work_dir):
        tool = FileReadTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="../../etc/passwd")
        assert result.success is False
        assert "denied" in result.error.lower()


class TestShellExecTool:
    async def test_run_command(self, tmp_work_dir):
        tool = ShellExecTool(base_dir=tmp_work_dir)
        result = await tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.output

    async def test_command_failure(self, tmp_work_dir):
        tool = ShellExecTool(base_dir=tmp_work_dir)
        result = await tool.execute(command="exit 1")
        assert result.success is False

    async def test_timeout(self, tmp_work_dir):
        tool = ShellExecTool(base_dir=tmp_work_dir, timeout=1)
        result = await tool.execute(command="sleep 10")
        assert result.success is False
        assert "timeout" in result.error.lower()


class TestWebFetchTool:
    async def test_fetch_url(self):
        tool = WebFetchTool()
        mock_response = AsyncMock()
        mock_response.text = "page content"
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        with patch("landlord.tools.web_fetch.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            result = await tool.execute(url="https://example.com")
            assert result.success is True
            assert result.output == "page content"


class TestWebSearchTool:
    async def test_search(self):
        tool = WebSearchTool(api_url="https://search.example.com")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"results": [{"title": "Result 1", "url": "https://example.com"}]}
        mock_response.raise_for_status = lambda: None

        with patch("landlord.tools.web_search.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            result = await tool.execute(query="python async")
            assert result.success is True
            assert "Result 1" in result.output

    async def test_search_no_api_url(self):
        tool = WebSearchTool(api_url=None, api_key=None)
        # Ensure env vars are not set
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SEARCH_API_URL", None)
            result = await tool.execute(query="something")
        assert result.success is False
        assert "api" in result.error.lower() or "configured" in result.error.lower()
```

- [ ] **Step 2: Run tests to verify they all fail (imports not yet created)**

Run: `pytest tests/test_tools.py -v 2>&1 | head -40`
Expected: `ImportError` or `ModuleNotFoundError` for `landlord.tools.file_write` etc.

---

### Task 3: Implement FileWriteTool

**Files:**
- Create: `landlord/tools/file_write.py`

- [ ] **Step 1: Create `landlord/tools/file_write.py`**

```python
"""File write tool for tenant workers."""
from __future__ import annotations

from pathlib import Path

from landlord.tools.base import ToolResult


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
```

- [ ] **Step 2: Run FileWriteTool tests**

Run: `pytest tests/test_tools.py::TestFileWriteTool -v`
Expected: All 3 tests PASS

---

### Task 4: Implement FileReadTool

**Files:**
- Create: `landlord/tools/file_read.py`

- [ ] **Step 1: Create `landlord/tools/file_read.py`**

```python
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
```

- [ ] **Step 2: Run FileReadTool tests**

Run: `pytest tests/test_tools.py::TestFileReadTool -v`
Expected: All 3 tests PASS

---

### Task 5: Implement ShellExecTool

**Files:**
- Create: `landlord/tools/shell_exec.py`

- [ ] **Step 1: Create `landlord/tools/shell_exec.py`**

```python
"""Shell execution tool for tenant workers."""
from __future__ import annotations

import asyncio
from pathlib import Path

from landlord.tools.base import ToolResult


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
```

- [ ] **Step 2: Run ShellExecTool tests**

Run: `pytest tests/test_tools.py::TestShellExecTool -v`
Expected: All 3 tests PASS

---

### Task 6: Implement WebFetchTool

**Files:**
- Create: `landlord/tools/web_fetch.py`

- [ ] **Step 1: Create `landlord/tools/web_fetch.py`**

```python
"""Web fetch tool for tenant workers."""
from __future__ import annotations

import httpx

from landlord.tools.base import ToolResult


class WebFetchTool:
    """Fetches content from a URL via HTTP GET."""

    name = "web_fetch"
    description = "Fetch the content of a URL via HTTP GET."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
        },
        "required": ["url"],
    }

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    async def execute(self, **kwargs) -> ToolResult:
        url: str = kwargs["url"]
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                return ToolResult(success=True, output=response.text)
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))
```

- [ ] **Step 2: Run WebFetchTool tests**

Run: `pytest tests/test_tools.py::TestWebFetchTool -v`
Expected: All 1 test PASS

---

### Task 7: Implement WebSearchTool

**Files:**
- Create: `landlord/tools/web_search.py`

- [ ] **Step 1: Create `landlord/tools/web_search.py`**

```python
"""Web search tool for tenant workers."""
from __future__ import annotations

import os

import httpx

from landlord.tools.base import ToolResult


class WebSearchTool:
    """Searches the web via a configured search API."""

    name = "web_search"
    description = "Search the web using a search API."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query string"},
        },
        "required": ["query"],
    }

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._api_url = api_url or os.environ.get("SEARCH_API_URL")
        self._api_key = api_key or os.environ.get("SEARCH_API_KEY")

    async def execute(self, **kwargs) -> ToolResult:
        query: str = kwargs["query"]
        if not self._api_url:
            return ToolResult(
                success=False,
                output="",
                error="No search API configured. Set SEARCH_API_URL or pass api_url.",
            )
        payload: dict = {"query": query}
        if self._api_key:
            payload["api_key"] = self._api_key
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self._api_url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

        results = data.get("results", [])
        lines = [f"{r.get('title', 'No title')}: {r.get('url', '')}" for r in results]
        return ToolResult(success=True, output="\n".join(lines))
```

- [ ] **Step 2: Run WebSearchTool tests**

Run: `pytest tests/test_tools.py::TestWebSearchTool -v`
Expected: All 2 tests PASS

---

### Task 8: Update tool registry in `__init__.py`

**Files:**
- Modify: `landlord/tools/__init__.py`

- [ ] **Step 1: Replace `landlord/tools/__init__.py` with registry**

```python
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
```

- [ ] **Step 2: Run all tool tests**

Run: `pytest tests/test_tools.py -v`
Expected: All tests PASS

---

### Task 9: Final verification and commit

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass, no regressions

- [ ] **Step 2: Commit all changes**

```bash
git add landlord/tools/file_write.py landlord/tools/file_read.py landlord/tools/shell_exec.py landlord/tools/web_fetch.py landlord/tools/web_search.py landlord/tools/__init__.py pyproject.toml tests/test_tools.py docs/superpowers/plans/2026-04-08-concrete-tools.md
git commit -m "feat: implement concrete tools (file_write, file_read, shell_exec, web_fetch, web_search) with registry"
```
