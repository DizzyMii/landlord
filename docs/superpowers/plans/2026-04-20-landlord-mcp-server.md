# Landlord MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first MCP server over stdio that exposes Landlord orchestration as a 5-tool async job API, with Claude Agent SDK-backed tenants, plan approval gating, and 2-tier checkpoint validation.

**Architecture:** New Python modules at `landlord/` root (`mcp_server.py`, `orchestrator.py`, `tenant.py`, `validator.py`, `jobs.py`, `anthropic_client.py`) sit on top of the unchanged `contract.py`. The old litellm-based runtime moves to `landlord/legacy/` so the existing CLI still works. Tenants are `claude_agent_sdk.ClaudeSDKClient` sessions with per-checkpoint synthetic tools exposed via an in-process SDK MCP server.

**Tech Stack:** Python 3.11+, `mcp` (MCP SDK), `claude-agent-sdk`, `anthropic`, `pydantic`, `jsonschema`, `pytest` + `pytest-asyncio` + `pytest-mock`.

**Spec reference:** `docs/superpowers/specs/2026-04-20-landlord-mcp-server-design.md`

**Working directory:** `C:/Users/KadeHeglin/Downloads/Projects/AI-and-Agents/Landlord Framework/`. All relative paths below are relative to this directory.

**Branch:** Work on the existing `feat/implement-framework` branch (already checked out).

---

## Task 1: Relocate legacy runtime to `landlord/legacy/`

This task is a refactor, not TDD. The goal: move the existing litellm-based code into a `legacy` sub-package so the new names (`landlord/tenant.py`, `landlord/validator.py`) are free for the new implementation. The old CLI (`landlord`) must keep working after this task.

**Files:**
- Create: `landlord/legacy/__init__.py`, `landlord/legacy/tools/__init__.py`
- Move: `landlord/cli.py`, `landlord/config.py`, `landlord/repl.py`, `landlord/renderer.py`, `landlord/dashboard.py`, `landlord/event_bus.py`, `landlord/llm_client.py`, `landlord/landlord.py`, `landlord/tenant.py`, `landlord/validator.py` → `landlord/legacy/`
- Move: `landlord/tools/*.py` → `landlord/legacy/tools/`
- Modify: all moved files — update `from landlord.X` imports to `from landlord.legacy.X`
- Modify: `pyproject.toml` (entry point, add `legacy` extra)
- Modify: `landlord/__init__.py`
- Move: `tests/test_cli.py`, `tests/test_config.py`, `tests/test_dashboard.py`, `tests/test_event_bus.py`, `tests/test_integration.py`, `tests/test_landlord.py`, `tests/test_llm_client.py`, `tests/test_renderer.py`, `tests/test_repl.py`, `tests/test_tenant.py`, `tests/test_tools.py`, `tests/test_validator.py` → `tests/legacy/`
- Create: `tests/legacy/__init__.py`, `tests/legacy/conftest.py`
- Modify: `pyproject.toml` pytest config to exclude `tests/legacy/` by default

**Keep at `landlord/` top level:** `__init__.py`, `contract.py`.

---

- [ ] **Step 1.1: Create the legacy package skeleton**

Run:
```bash
cd "C:/Users/KadeHeglin/Downloads/Projects/AI-and-Agents/Landlord Framework"
mkdir -p landlord/legacy/tools
```

Create `landlord/legacy/__init__.py`:
```python
"""Legacy litellm-based Landlord runtime, preserved for the old CLI."""
```

Create `landlord/legacy/tools/__init__.py`:
```python
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
```

- [ ] **Step 1.2: Move modules with `git mv` to preserve history**

Run (from repo root):
```bash
git mv landlord/cli.py landlord/legacy/cli.py
git mv landlord/config.py landlord/legacy/config.py
git mv landlord/repl.py landlord/legacy/repl.py
git mv landlord/renderer.py landlord/legacy/renderer.py
git mv landlord/dashboard.py landlord/legacy/dashboard.py
git mv landlord/event_bus.py landlord/legacy/event_bus.py
git mv landlord/llm_client.py landlord/legacy/llm_client.py
git mv landlord/landlord.py landlord/legacy/landlord.py
git mv landlord/tenant.py landlord/legacy/tenant.py
git mv landlord/validator.py landlord/legacy/validator.py
git mv landlord/tools/base.py landlord/legacy/tools/base.py
git mv landlord/tools/file_write.py landlord/legacy/tools/file_write.py
git mv landlord/tools/file_read.py landlord/legacy/tools/file_read.py
git mv landlord/tools/shell_exec.py landlord/legacy/tools/shell_exec.py
git mv landlord/tools/web_fetch.py landlord/legacy/tools/web_fetch.py
git mv landlord/tools/web_search.py landlord/legacy/tools/web_search.py
```

Overwrite `landlord/legacy/tools/__init__.py` with the content from Step 1.1 (git mv of the old `__init__.py` would conflict — delete the moved one if any, then write the new content above).

Delete (if present):
```bash
rm -f landlord/tools/__init__.py
rmdir landlord/tools 2>/dev/null || true
```

- [ ] **Step 1.3: Update imports in all moved modules**

In each moved file under `landlord/legacy/`, replace every import that starts with `from landlord.` or `import landlord.` so that it references `landlord.legacy.` — except imports of `landlord.contract` (which stays at top level) and `landlord` itself (e.g., `import landlord` for `__version__`).

Apply these exact replacements across every file in `landlord/legacy/` and `landlord/legacy/tools/`:

| Old import | New import |
|---|---|
| `from landlord.config` | `from landlord.legacy.config` |
| `from landlord.event_bus` | `from landlord.legacy.event_bus` |
| `from landlord.llm_client` | `from landlord.legacy.llm_client` |
| `from landlord.landlord` | `from landlord.legacy.landlord` |
| `from landlord.tenant` | `from landlord.legacy.tenant` |
| `from landlord.validator` | `from landlord.legacy.validator` |
| `from landlord.renderer` | `from landlord.legacy.renderer` |
| `from landlord.dashboard` | `from landlord.legacy.dashboard` |
| `from landlord.repl` | `from landlord.legacy.repl` |
| `from landlord.cli` | `from landlord.legacy.cli` |
| `from landlord.tools` | `from landlord.legacy.tools` |
| `from landlord.tools.base` | `from landlord.legacy.tools.base` |

Leave these imports unchanged:
- `from landlord.contract import ...` — Contract stays at top level.
- `import landlord` — package-level version import.

Use Grep to confirm after the edits:
```bash
grep -rn "from landlord\." landlord/legacy/ | grep -v "landlord.legacy" | grep -v "landlord.contract"
```
Expected: no output.

- [ ] **Step 1.4: Update `pyproject.toml`**

Replace the `[project.scripts]`, `[project.optional-dependencies]`, and `[tool.pytest.ini_options]` sections. Full intended content of `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "landlord-framework"
version = "0.2.0"
description = "An agentic AI framework with contract-based orchestration, exposed as an MCP server."
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0",
    "anthropic>=0.40",
    "claude-agent-sdk>=0.1",
    "pydantic>=2.0",
    "jsonschema>=4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "ruff>=0.4",
]
legacy = [
    "litellm>=1.40",
    "typer>=0.12",
    "rich>=13.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.scripts]
landlord-mcp = "landlord.mcp_server:main"
landlord = "landlord.legacy.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["landlord"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
norecursedirs = ["tests/legacy"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

The `landlord-mcp` entry point is the new MCP server binary. The `landlord` entry point still runs the old CLI (imports from legacy).

- [ ] **Step 1.5: Update `landlord/__init__.py`**

Replace file contents with:
```python
"""Landlord Framework — contract-based agent orchestration as an MCP server."""

__version__ = "0.2.0"
```

- [ ] **Step 1.6: Relocate legacy tests**

Run (from repo root):
```bash
mkdir -p tests/legacy
git mv tests/test_cli.py tests/legacy/test_cli.py
git mv tests/test_config.py tests/legacy/test_config.py
git mv tests/test_dashboard.py tests/legacy/test_dashboard.py
git mv tests/test_event_bus.py tests/legacy/test_event_bus.py
git mv tests/test_integration.py tests/legacy/test_integration.py
git mv tests/test_landlord.py tests/legacy/test_landlord.py
git mv tests/test_llm_client.py tests/legacy/test_llm_client.py
git mv tests/test_renderer.py tests/legacy/test_renderer.py
git mv tests/test_repl.py tests/legacy/test_repl.py
git mv tests/test_tenant.py tests/legacy/test_tenant.py
git mv tests/test_tools.py tests/legacy/test_tools.py
git mv tests/test_validator.py tests/legacy/test_validator.py
```

Create `tests/legacy/__init__.py` (empty file).

Create `tests/legacy/conftest.py`:
```python
"""Conftest for legacy tests. Makes the tmp_work_dir fixture available here too."""
from tests.conftest import tmp_work_dir  # re-export

__all__ = ["tmp_work_dir"]
```

In each moved test file under `tests/legacy/`, apply the same import rewrite as Step 1.3 (e.g., `from landlord.tenant` → `from landlord.legacy.tenant`). Leave `from landlord.contract` imports alone.

- [ ] **Step 1.7: Verify the package still imports**

Run:
```bash
python -c "from landlord.legacy.cli import app; from landlord.contract import Contract, Checkpoint; print('OK')"
```
Expected output: `OK`

If this fails with an ImportError, fix the offending import in the referenced file before proceeding.

- [ ] **Step 1.8: Run the retained test_contract.py**

Run:
```bash
pip install -e ".[dev,legacy]"
pytest tests/test_contract.py -v
```
Expected: all tests in `test_contract.py` pass. Legacy tests are excluded by `norecursedirs`, so they will not run.

- [ ] **Step 1.9: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor: move legacy litellm runtime to landlord/legacy/

Frees the landlord/ top-level namespace for the new MCP-server runtime
modules (mcp_server, orchestrator, tenant, validator, jobs, anthropic_client).
Old CLI still works via the landlord entry point (now landlord.legacy.cli:app).
Legacy tests relocated to tests/legacy/ and excluded from default pytest.

EOF
)"
```

---

## Task 2: `anthropic_client.py` — thin wrapper with cache_control

A minimal wrapper around the official `anthropic` SDK that adds three conveniences: (a) applying `cache_control: {type: "ephemeral"}` to specified system-prompt blocks, (b) calling a tool with `tool_choice` forced to that tool so the model always returns structured output, (c) tracking token usage with cache-hit visibility.

**Files:**
- Create: `landlord/anthropic_client.py`
- Test: `tests/test_anthropic_client.py`

- [ ] **Step 2.1: Write the failing test — cached system block shape**

Create `tests/test_anthropic_client.py`:

```python
"""Tests for the thin Anthropic SDK wrapper."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.anthropic_client import AnthropicClient, CachedBlock


@pytest.mark.asyncio
async def test_messages_applies_cache_control_to_system_blocks(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="hello")]
    fake_response.stop_reason = "end_turn"
    fake_response.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    system_blocks = [
        CachedBlock(text="You are a helpful assistant.", cache=True),
        CachedBlock(text="Additional context that is not cached.", cache=False),
    ]
    await client.messages(system=system_blocks, messages=[{"role": "user", "content": "hi"}])

    sent_system = fake_sdk.messages.create.call_args.kwargs["system"]
    assert sent_system == [
        {"type": "text", "text": "You are a helpful assistant.", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Additional context that is not cached."},
    ]
```

- [ ] **Step 2.2: Run — verify failure**

Run:
```bash
pytest tests/test_anthropic_client.py::test_messages_applies_cache_control_to_system_blocks -v
```
Expected: FAIL with `ImportError` or `ModuleNotFoundError` for `landlord.anthropic_client`.

- [ ] **Step 2.3: Write the initial `anthropic_client.py`**

Create `landlord/anthropic_client.py`:

```python
"""Thin Anthropic SDK wrapper with cache_control, forced tool use, and usage tracking."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
```

- [ ] **Step 2.4: Run — verify Step 2.1 passes**

Run:
```bash
pytest tests/test_anthropic_client.py::test_messages_applies_cache_control_to_system_blocks -v
```
Expected: PASS.

- [ ] **Step 2.5: Add the forced-tool test**

Append to `tests/test_anthropic_client.py`:

```python
@pytest.mark.asyncio
async def test_call_forced_tool_returns_parsed_arguments(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "judge_checkpoint"
    tool_block.input = {"passed": True, "reason": "looks good"}
    fake_response.content = [tool_block]
    fake_response.stop_reason = "tool_use"
    fake_response.usage = MagicMock(
        input_tokens=10, output_tokens=5,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    tool = {
        "name": "judge_checkpoint",
        "description": "Judge whether the output meets the criterion.",
        "input_schema": {
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["passed", "reason"],
        },
    }
    result = await client.call_forced_tool(
        system=[CachedBlock(text="You are a judge.", cache=True)],
        messages=[{"role": "user", "content": "judge this"}],
        tool=tool,
    )
    assert result == {"passed": True, "reason": "looks good"}
    call = fake_sdk.messages.create.call_args.kwargs
    assert call["tool_choice"] == {"type": "tool", "name": "judge_checkpoint"}
    assert call["tools"] == [tool]


@pytest.mark.asyncio
async def test_call_forced_tool_raises_when_tool_not_called(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    text_block = MagicMock(type="text", text="I refuse")
    fake_response.content = [text_block]
    fake_response.stop_reason = "end_turn"
    fake_response.usage = MagicMock(
        input_tokens=5, output_tokens=3,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    tool = {
        "name": "judge_checkpoint",
        "description": "Judge.",
        "input_schema": {"type": "object", "properties": {"passed": {"type": "boolean"}}, "required": ["passed"]},
    }
    with pytest.raises(RuntimeError, match="did not call forced tool"):
        await client.call_forced_tool(
            system=[CachedBlock(text="Judge.", cache=True)],
            messages=[{"role": "user", "content": "x"}],
            tool=tool,
        )


@pytest.mark.asyncio
async def test_usage_stats_accumulate(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="ok")]
    fake_response.stop_reason = "end_turn"
    fake_response.usage = MagicMock(
        input_tokens=100, output_tokens=50,
        cache_creation_input_tokens=200, cache_read_input_tokens=300,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    await client.messages(system=[CachedBlock(text="s", cache=True)], messages=[{"role": "user", "content": "hi"}])
    await client.messages(system=[CachedBlock(text="s", cache=True)], messages=[{"role": "user", "content": "hi"}])
    assert client.usage.input_tokens == 200
    assert client.usage.output_tokens == 100
    assert client.usage.cache_creation_input_tokens == 400
    assert client.usage.cache_read_input_tokens == 600
```

- [ ] **Step 2.6: Run — full test file passes**

Run:
```bash
pytest tests/test_anthropic_client.py -v
```
Expected: 4 tests pass.

- [ ] **Step 2.7: Commit**

```bash
git add landlord/anthropic_client.py tests/test_anthropic_client.py
git commit -m "$(cat <<'EOF'
feat: add AnthropicClient wrapper with cache_control + forced tool use

Thin async wrapper over the anthropic SDK that (a) renders system-prompt
blocks with cache_control: ephemeral markers, (b) forces tool use via
tool_choice to guarantee structured output, (c) accumulates usage stats
with cache-hit visibility.

EOF
)"
```

---

## Task 3: `jobs.py` — Job, TenantState, JobRegistry

In-memory job registry with state transitions, JSON sidecar persistence, and safe concurrent access via `asyncio.Lock`.

**Files:**
- Create: `landlord/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 3.1: Write the first failing test — Job creation and initial state**

Create `tests/test_jobs.py`:

```python
"""Tests for the in-memory job registry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.jobs import Job, JobRegistry, TenantState


def _simple_contract(role: str, depends_on: list[str] | None = None) -> Contract:
    return Contract(
        role=role,
        objective=f"objective for {role}",
        sub_prompt="do the thing",
        checkpoints=[Checkpoint(
            name="done",
            description="final result",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        )],
        output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        depends_on=depends_on or [],
    )


def test_job_creation_starts_in_awaiting_approval(tmp_path: Path):
    plan = [_simple_contract("worker")]
    job = Job.create(prompt="do something", plan=plan, output_dir=tmp_path)

    assert job.status == "awaiting_approval"
    assert job.prompt == "do something"
    assert len(job.plan) == 1
    assert job.plan[0].role == "worker"
    assert set(job.tenants.keys()) == {plan[0].tenant_id}
    assert job.tenants[plan[0].tenant_id].status == "pending"
    assert job.tenants[plan[0].tenant_id].retry_count == 0
    assert job.artifacts == {}
    assert len(job.job_id) == 8
```

- [ ] **Step 3.2: Run — verify failure**

Run:
```bash
pytest tests/test_jobs.py -v
```
Expected: FAIL with `ImportError: cannot import name 'Job' from 'landlord.jobs'`.

- [ ] **Step 3.3: Write minimal `jobs.py`**

Create `landlord/jobs.py`:

```python
"""In-memory job registry with JSON sidecar persistence."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from landlord.contract import Contract


JobStatus = str  # "awaiting_approval" | "running" | "complete" | "partial" | "cancelled"
TenantStatusLiteral = str  # "pending" | "running" | "complete" | "evicted" | "escalated"


@dataclass
class TenantState:
    contract: Contract
    status: TenantStatusLiteral = "pending"
    checkpoints_passed: list[str] = field(default_factory=list)
    retry_count: int = 0
    last_error: str | None = None
    task: asyncio.Task | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.contract.role,
            "tenant_id": self.contract.tenant_id,
            "status": self.status,
            "checkpoints_passed": list(self.checkpoints_passed),
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }


@dataclass
class Job:
    job_id: str
    prompt: str
    plan: list[Contract]
    output_dir: Path
    status: JobStatus = "awaiting_approval"
    tenants: dict[str, TenantState] = field(default_factory=dict)
    artifacts: dict[str, dict] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None

    @classmethod
    def create(cls, prompt: str, plan: list[Contract], output_dir: Path) -> Job:
        job_id = uuid4().hex[:8]
        job_dir = output_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "shared").mkdir(exist_ok=True)
        tenants = {c.tenant_id: TenantState(contract=c) for c in plan}
        return cls(
            job_id=job_id,
            prompt=prompt,
            plan=list(plan),
            output_dir=job_dir,
            tenants=tenants,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "prompt": self.prompt,
            "status": self.status,
            "plan": [c.model_dump() for c in self.plan],
            "tenants": [t.to_dict() for t in self.tenants.values()],
            "artifacts": dict(self.artifacts),
            "created_at": self.created_at,
            "approved_at": self.approved_at,
        }

    def write_sidecar(self) -> None:
        (self.output_dir / "job.json").write_text(json.dumps(self.to_dict(), indent=2))


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, prompt: str, plan: list[Contract], output_dir: Path) -> Job:
        job = Job.create(prompt=prompt, plan=plan, output_dir=output_dir)
        async with self._lock:
            self._jobs[job.job_id] = job
        job.write_sidecar()
        return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def transition(self, job_id: str, new_status: JobStatus) -> Job:
        async with self._lock:
            job = self._jobs[job_id]
            job.status = new_status
            if new_status == "running" and job.approved_at is None:
                job.approved_at = time.time()
        job.write_sidecar()
        return job

    async def replace_plan(self, job_id: str, new_plan: list[Contract]) -> Job:
        async with self._lock:
            job = self._jobs[job_id]
            job.plan = list(new_plan)
            job.tenants = {c.tenant_id: TenantState(contract=c) for c in new_plan}
        job.write_sidecar()
        return job

    def all_ids(self) -> list[str]:
        return list(self._jobs.keys())
```

- [ ] **Step 3.4: Run — verify test passes**

Run:
```bash
pytest tests/test_jobs.py::test_job_creation_starts_in_awaiting_approval -v
```
Expected: PASS.

- [ ] **Step 3.5: Add state transition tests**

Append to `tests/test_jobs.py`:

```python
@pytest.mark.asyncio
async def test_registry_create_writes_sidecar(tmp_path: Path):
    reg = JobRegistry()
    plan = [_simple_contract("writer")]
    job = await reg.create_job(prompt="p", plan=plan, output_dir=tmp_path)

    sidecar = job.output_dir / "job.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["status"] == "awaiting_approval"
    assert data["prompt"] == "p"
    assert len(data["plan"]) == 1


@pytest.mark.asyncio
async def test_registry_transition_sets_approved_at_on_running(tmp_path: Path):
    reg = JobRegistry()
    job = await reg.create_job(prompt="p", plan=[_simple_contract("a")], output_dir=tmp_path)
    assert job.approved_at is None

    await reg.transition(job.job_id, "running")
    fetched = await reg.get(job.job_id)
    assert fetched is not None
    assert fetched.status == "running"
    assert fetched.approved_at is not None


@pytest.mark.asyncio
async def test_registry_replace_plan_resets_tenants(tmp_path: Path):
    reg = JobRegistry()
    original_plan = [_simple_contract("a"), _simple_contract("b")]
    job = await reg.create_job(prompt="p", plan=original_plan, output_dir=tmp_path)
    original_tenant_ids = set(job.tenants.keys())

    new_plan = [_simple_contract("c")]
    await reg.replace_plan(job.job_id, new_plan)
    fetched = await reg.get(job.job_id)
    assert fetched is not None
    assert len(fetched.tenants) == 1
    assert set(fetched.tenants.keys()) != original_tenant_ids
    assert fetched.plan[0].role == "c"


@pytest.mark.asyncio
async def test_registry_get_returns_none_for_unknown_id():
    reg = JobRegistry()
    assert await reg.get("nonexistent") is None


@pytest.mark.asyncio
async def test_tenant_state_to_dict_roundtrip(tmp_path: Path):
    plan = [_simple_contract("a")]
    job = Job.create(prompt="p", plan=plan, output_dir=tmp_path)
    tenant = job.tenants[plan[0].tenant_id]
    tenant.status = "running"
    tenant.checkpoints_passed.append("done")
    tenant.retry_count = 1
    tenant.last_error = "nope"

    d = tenant.to_dict()
    assert d == {
        "role": "a",
        "tenant_id": plan[0].tenant_id,
        "status": "running",
        "checkpoints_passed": ["done"],
        "retry_count": 1,
        "last_error": "nope",
    }
```

- [ ] **Step 3.6: Run — all job tests pass**

Run:
```bash
pytest tests/test_jobs.py -v
```
Expected: 5 tests pass.

- [ ] **Step 3.7: Commit**

```bash
git add landlord/jobs.py tests/test_jobs.py
git commit -m "$(cat <<'EOF'
feat: add JobRegistry with in-memory state + JSON sidecar

Job, TenantState, JobRegistry with asyncio.Lock-guarded mutations.
Sidecar written on create, transition, and plan replacement. No
recovery — sidecar is inspection-only per the v1 spec.

EOF
)"
```

---

## Task 4: `validator.py` — 2-tier checkpoint validation

Tier 1 = JSON Schema. Tier 2 = structured LLM judge via forced tool use. Fails fast on Tier 1.

**Files:**
- Create: `landlord/validator.py` (at top level — the legacy one moved to `landlord/legacy/validator.py` in Task 1)
- Test: `tests/test_validator.py` (the old one moved to `tests/legacy/test_validator.py` in Task 1)

- [ ] **Step 4.1: Write the failing test — Tier 1 pass**

Create `tests/test_validator.py`:

```python
"""Tests for the 2-tier checkpoint validator."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.validator import ValidationResult, Validator


def _contract(role: str = "worker") -> Contract:
    return Contract(
        role=role,
        objective="obj",
        sub_prompt="prompt",
        checkpoints=[],
        output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    )


def _checkpoint(schema: dict | None = None) -> Checkpoint:
    return Checkpoint(
        name="done",
        description="the tenant has finished",
        schema=schema or {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    )


@pytest.mark.asyncio
async def test_tier1_schema_validation_passes_and_runs_tier2():
    mock_client = MagicMock()
    mock_client.call_forced_tool = AsyncMock(return_value={"passed": True, "reason": "ok"})

    validator = Validator(client=mock_client)
    result = await validator.validate_checkpoint(
        output={"x": "hello"},
        checkpoint=_checkpoint(),
        contract=_contract(),
    )

    assert isinstance(result, ValidationResult)
    assert result.passed is True
    assert result.tier == 2
    assert "ok" in result.explanation
    mock_client.call_forced_tool.assert_awaited_once()
```

- [ ] **Step 4.2: Run — verify failure**

Run:
```bash
pytest tests/test_validator.py::test_tier1_schema_validation_passes_and_runs_tier2 -v
```
Expected: FAIL with `ImportError` for `landlord.validator`.

- [ ] **Step 4.3: Write minimal `validator.py`**

Create `landlord/validator.py`:

```python
"""Two-tier checkpoint validator: JSON Schema + structured LLM judge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import jsonschema

from landlord.anthropic_client import AnthropicClient, CachedBlock
from landlord.contract import Checkpoint, Contract


@dataclass
class ValidationResult:
    passed: bool
    tier: int
    explanation: str
    errors: list[str] = field(default_factory=list)


JUDGE_SYSTEM = (
    "You are a strict validator. You receive a checkpoint output from a worker agent "
    "along with the contract objective and the checkpoint description. You must decide "
    "whether the output meets the intent of the checkpoint and call the judge_checkpoint "
    "tool with your verdict. Be lenient on form, strict on substance: if the worker "
    "produced something that factually satisfies the checkpoint description, pass. If it "
    "is missing required work, off-topic, or trivially incorrect, fail with a concrete "
    "reason."
)

JUDGE_TOOL = {
    "name": "judge_checkpoint",
    "description": "Record whether the checkpoint output meets the requirements.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["passed", "reason"],
    },
}


class Validator:
    def __init__(self, client: AnthropicClient) -> None:
        self._client = client

    async def validate_checkpoint(
        self,
        output: dict,
        checkpoint: Checkpoint,
        contract: Contract,
    ) -> ValidationResult:
        tier1 = self._validate_schema(output, checkpoint)
        if not tier1.passed:
            return tier1
        return await self._validate_semantic(output, checkpoint, contract)

    def _validate_schema(self, output: dict, checkpoint: Checkpoint) -> ValidationResult:
        try:
            jsonschema.validate(instance=output, schema=checkpoint.schema)
            return ValidationResult(
                passed=True, tier=1, explanation="Schema validation passed"
            )
        except jsonschema.ValidationError as e:
            return ValidationResult(
                passed=False,
                tier=1,
                explanation=f"Schema validation failed: {e.message}",
                errors=[e.message],
            )

    async def _validate_semantic(
        self, output: dict, checkpoint: Checkpoint, contract: Contract
    ) -> ValidationResult:
        system = [CachedBlock(text=JUDGE_SYSTEM, cache=True)]
        user_content = (
            f"Contract objective: {contract.objective}\n"
            f"Checkpoint name: {checkpoint.name}\n"
            f"Checkpoint description: {checkpoint.description}\n"
            f"Output:\n{json.dumps(output, indent=2, default=str)}"
        )
        verdict = await self._client.call_forced_tool(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tool=JUDGE_TOOL,
        )
        return ValidationResult(
            passed=bool(verdict.get("passed", False)),
            tier=2,
            explanation=str(verdict.get("reason", "")),
        )
```

- [ ] **Step 4.4: Run — verify Step 4.1 passes**

Run:
```bash
pytest tests/test_validator.py::test_tier1_schema_validation_passes_and_runs_tier2 -v
```
Expected: PASS.

- [ ] **Step 4.5: Add Tier 1 failure test (short-circuit)**

Append to `tests/test_validator.py`:

```python
@pytest.mark.asyncio
async def test_tier1_failure_skips_tier2():
    mock_client = MagicMock()
    mock_client.call_forced_tool = AsyncMock()

    validator = Validator(client=mock_client)
    result = await validator.validate_checkpoint(
        output={"wrong_field": 1},  # missing required "x"
        checkpoint=_checkpoint(),
        contract=_contract(),
    )

    assert result.passed is False
    assert result.tier == 1
    assert "Schema validation failed" in result.explanation
    assert result.errors  # contains jsonschema error message
    mock_client.call_forced_tool.assert_not_called()


@pytest.mark.asyncio
async def test_tier2_fail_returns_reason():
    mock_client = MagicMock()
    mock_client.call_forced_tool = AsyncMock(
        return_value={"passed": False, "reason": "output is off-topic"}
    )

    validator = Validator(client=mock_client)
    result = await validator.validate_checkpoint(
        output={"x": "hello"},
        checkpoint=_checkpoint(),
        contract=_contract(),
    )

    assert result.passed is False
    assert result.tier == 2
    assert result.explanation == "output is off-topic"


@pytest.mark.asyncio
async def test_judge_call_uses_cached_system_and_forced_tool():
    mock_client = MagicMock()
    mock_client.call_forced_tool = AsyncMock(return_value={"passed": True, "reason": "ok"})

    validator = Validator(client=mock_client)
    await validator.validate_checkpoint(
        output={"x": "hello"},
        checkpoint=_checkpoint(),
        contract=_contract(),
    )

    call = mock_client.call_forced_tool.call_args
    system_blocks = call.kwargs["system"]
    assert len(system_blocks) == 1
    assert system_blocks[0].cache is True
    assert call.kwargs["tool"]["name"] == "judge_checkpoint"
```

- [ ] **Step 4.6: Run — full validator suite passes**

Run:
```bash
pytest tests/test_validator.py -v
```
Expected: 4 tests pass.

- [ ] **Step 4.7: Commit**

```bash
git add landlord/validator.py tests/test_validator.py
git commit -m "$(cat <<'EOF'
feat: add 2-tier Validator using AnthropicClient for the judge

Tier 1 is jsonschema.validate. Tier 2 forces tool use on judge_checkpoint
so the verdict is always {passed: bool, reason: str} — no substring
matching. Tier 1 short-circuits on failure. Judge system prompt is
cached.

EOF
)"
```

---

## Task 5: `tenant.py` — Agent SDK session runner with checkpoint hooks

Each tenant is one `asyncio.Task` that (a) builds an SDK session config from its Contract, (b) exposes per-checkpoint synthetic tools via an in-process SDK MCP server, (c) routes checkpoint tool calls through the Validator and returns pass/fail to the tenant, (d) signals completion by either finishing normally or being cancelled mid-session by the orchestrator.

For testability, the SDK session is a thin wrapper that delegates to `claude_agent_sdk.ClaudeSDKClient`. Tests use a fake SDK client injected at construction time; production wires the real SDK.

**Files:**
- Create: `landlord/tenant.py`
- Test: `tests/test_tenant.py`

- [ ] **Step 5.1: Write the first failing test — building session config**

Create `tests/test_tenant.py`:

```python
"""Tests for the Claude Agent SDK-backed tenant runner."""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.tenant import (
    CHECKPOINT_TOOL_PREFIX,
    TenantRunner,
    build_system_prompt,
    sanitize_tool_name,
)


def _contract(role: str = "worker", checkpoints: list[Checkpoint] | None = None) -> Contract:
    return Contract(
        role=role,
        objective=f"ship {role}",
        sub_prompt=f"do the {role} task",
        checkpoints=checkpoints or [Checkpoint(
            name="artifact ready",
            description="the artifact is complete and written to disk",
            schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        )],
        output_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )


def test_sanitize_tool_name_strips_disallowed_chars():
    assert sanitize_tool_name("artifact ready") == "artifact_ready"
    assert sanitize_tool_name("step 1: scaffold!") == "step_1__scaffold_"
    assert sanitize_tool_name("already-ok_name") == "already-ok_name"


def test_build_system_prompt_includes_role_and_checkpoints():
    c = _contract()
    prompt = build_system_prompt(contract=c, shared_context=None, retry_context=None)
    assert "worker" in prompt
    assert "ship worker" in prompt
    assert "artifact ready" in prompt
    assert f"{CHECKPOINT_TOOL_PREFIX}artifact_ready" in prompt


def test_build_system_prompt_includes_shared_context_when_present():
    c = _contract()
    prompt = build_system_prompt(
        contract=c,
        shared_context="Dependencies produced:\n  schema.sql: CREATE TABLE ...",
        retry_context=None,
    )
    assert "schema.sql" in prompt


def test_build_system_prompt_includes_retry_context_when_present():
    c = _contract()
    prompt = build_system_prompt(
        contract=c,
        shared_context=None,
        retry_context="Previous attempt failed: wrong format.",
    )
    assert "wrong format" in prompt
```

- [ ] **Step 5.2: Run — verify failure**

Run:
```bash
pytest tests/test_tenant.py::test_sanitize_tool_name_strips_disallowed_chars -v
```
Expected: FAIL with `ImportError` for `landlord.tenant`.

- [ ] **Step 5.3: Scaffold `tenant.py` with pure helpers**

Create `landlord/tenant.py`:

```python
"""Agent-SDK-backed tenant runner with per-checkpoint synthetic tools."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from landlord.contract import Checkpoint, Contract


CHECKPOINT_TOOL_PREFIX = "emit_checkpoint__"


def sanitize_tool_name(name: str) -> str:
    """Coerce an arbitrary checkpoint name into a valid tool name."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def checkpoint_tool_name(cp: Checkpoint) -> str:
    return f"{CHECKPOINT_TOOL_PREFIX}{sanitize_tool_name(cp.name)}"


def build_system_prompt(
    contract: Contract,
    shared_context: str | None,
    retry_context: str | None,
) -> str:
    parts = [
        f"You are a {contract.role}.",
        f"Objective: {contract.objective}",
    ]
    if contract.checkpoints:
        cp_lines = []
        for cp in contract.checkpoints:
            cp_lines.append(
                f"- {cp.name}: call tool `{checkpoint_tool_name(cp)}` when {cp.description}"
            )
        parts.append(
            "Checkpoints — each has a dedicated tool; call it with the required fields "
            "when you reach that checkpoint:\n" + "\n".join(cp_lines)
        )
    parts.append(
        "You also have filesystem and bash tools, sandboxed to your working directory. "
        "Write files, read files, run commands freely. The checkpoint tools are how you "
        "declare structured results back to the orchestrator."
    )
    if shared_context:
        parts.append(f"Context from dependencies:\n{shared_context}")
    if retry_context:
        parts.append(f"Retry context — previous attempt failed:\n{retry_context}")
    return "\n\n".join(parts)


CheckpointHandler = Callable[[str, dict[str, Any]], Awaitable["CheckpointVerdict"]]


@dataclass
class CheckpointVerdict:
    passed: bool
    reason: str


@dataclass
class TenantResult:
    status: str  # "complete" | "evicted"
    reason: str | None = None
    last_output: dict | None = None


class TenantRunner:
    """Runs a single tenant SDK session.

    `sdk_session_factory` is a callable that receives (system_prompt, checkpoint_tool_defs,
    work_dir, model) and returns an object with async `run(sub_prompt, on_checkpoint)` — an
    injection seam so tests can substitute a fake for the real Claude Agent SDK session.
    """

    def __init__(
        self,
        contract: Contract,
        work_dir: Path,
        checkpoint_handler: CheckpointHandler,
        sdk_session_factory: Callable[..., Any],
        model: str,
        shared_context: str | None = None,
        retry_context: str | None = None,
    ) -> None:
        self._contract = contract
        self._work_dir = work_dir
        self._on_checkpoint = checkpoint_handler
        self._sdk_factory = sdk_session_factory
        self._model = model
        self._shared_context = shared_context
        self._retry_context = retry_context

    def build_checkpoint_tool_defs(self) -> list[dict[str, Any]]:
        defs = []
        for cp in self._contract.checkpoints:
            schema = cp.schema if cp.schema.get("type") == "object" else {
                "type": "object",
                "properties": {"result": cp.schema},
                "required": ["result"],
            }
            defs.append({
                "name": checkpoint_tool_name(cp),
                "description": (
                    f"Declare checkpoint '{cp.name}' reached: {cp.description}. "
                    "Call this with the required fields to record your output."
                ),
                "input_schema": schema,
            })
        return defs

    async def run(self) -> TenantResult:
        system_prompt = build_system_prompt(
            contract=self._contract,
            shared_context=self._shared_context,
            retry_context=self._retry_context,
        )
        tool_defs = self.build_checkpoint_tool_defs()
        session = self._sdk_factory(
            system_prompt=system_prompt,
            checkpoint_tools=tool_defs,
            work_dir=self._work_dir,
            model=self._model,
        )

        last_output: dict | None = None

        async def on_checkpoint_tool_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            nonlocal last_output
            if not tool_name.startswith(CHECKPOINT_TOOL_PREFIX):
                return {"ok": False, "error": f"Unknown tool {tool_name}"}
            sanitized = tool_name[len(CHECKPOINT_TOOL_PREFIX):]
            cp_name = next(
                (cp.name for cp in self._contract.checkpoints if sanitize_tool_name(cp.name) == sanitized),
                sanitized,
            )
            verdict = await self._on_checkpoint(cp_name, args)
            if verdict.passed:
                last_output = args
                return {"ok": True, "message": f"Checkpoint '{cp_name}' passed"}
            return {
                "ok": False,
                "message": f"Checkpoint '{cp_name}' failed: {verdict.reason}. Revise your work and try again.",
            }

        try:
            await session.run(
                sub_prompt=self._contract.sub_prompt,
                on_checkpoint=on_checkpoint_tool_call,
            )
        except asyncio.CancelledError:
            return TenantResult(status="evicted", reason="cancelled", last_output=last_output)

        return TenantResult(status="complete", last_output=last_output)
```

- [ ] **Step 5.4: Run — first four tests pass**

Run:
```bash
pytest tests/test_tenant.py -v
```
Expected: 4 tests pass (sanitize + 3 system-prompt builders).

- [ ] **Step 5.5: Add tests for `TenantRunner.run` with a fake SDK session**

Append to `tests/test_tenant.py`:

```python
class FakeSDKSession:
    """Stand-in for the Claude Agent SDK session used in tests.

    The orchestrator-under-test drives us via `run(sub_prompt, on_checkpoint)`.
    We replay a scripted list of checkpoint-tool calls and then return.
    """

    def __init__(self, scripted_calls: list[tuple[str, dict]]):
        self._calls = scripted_calls
        self.calls_made: list[tuple[str, dict]] = []
        self.last_system_prompt: str | None = None
        self.last_tool_defs: list | None = None

    async def run(self, sub_prompt: str, on_checkpoint):
        for tool_name, args in self._calls:
            self.calls_made.append((tool_name, args))
            result = await on_checkpoint(tool_name, args)
            if not result.get("ok"):
                return


def _factory(session: FakeSDKSession):
    def factory(system_prompt, checkpoint_tools, work_dir, model):
        session.last_system_prompt = system_prompt
        session.last_tool_defs = checkpoint_tools
        return session
    return factory


@pytest.mark.asyncio
async def test_tenant_run_passes_checkpoint_and_records_output(tmp_path: Path):
    c = _contract()
    fake_session = FakeSDKSession(scripted_calls=[
        ("emit_checkpoint__artifact_ready", {"path": "result.txt"}),
    ])
    handler_calls: list = []

    async def handler(name, args):
        handler_calls.append((name, args))
        from landlord.tenant import CheckpointVerdict
        return CheckpointVerdict(passed=True, reason="ok")

    runner = TenantRunner(
        contract=c,
        work_dir=tmp_path,
        checkpoint_handler=handler,
        sdk_session_factory=_factory(fake_session),
        model="claude-sonnet-4-6",
    )
    result = await runner.run()

    assert result.status == "complete"
    assert result.last_output == {"path": "result.txt"}
    assert handler_calls == [("artifact ready", {"path": "result.txt"})]
    assert fake_session.last_tool_defs is not None
    assert fake_session.last_tool_defs[0]["name"] == "emit_checkpoint__artifact_ready"


@pytest.mark.asyncio
async def test_tenant_run_returns_early_when_checkpoint_fails(tmp_path: Path):
    c = _contract()
    fake_session = FakeSDKSession(scripted_calls=[
        ("emit_checkpoint__artifact_ready", {"path": "result.txt"}),
        ("emit_checkpoint__artifact_ready", {"path": "should-not-run.txt"}),
    ])

    async def handler(name, args):
        from landlord.tenant import CheckpointVerdict
        return CheckpointVerdict(passed=False, reason="wrong format")

    runner = TenantRunner(
        contract=c,
        work_dir=tmp_path,
        checkpoint_handler=handler,
        sdk_session_factory=_factory(fake_session),
        model="claude-sonnet-4-6",
    )
    result = await runner.run()

    # Runner itself keeps status="complete" because the session exited cleanly;
    # eviction is decided by the orchestrator based on the failed verdict.
    assert result.status == "complete"
    assert result.last_output is None
    assert fake_session.calls_made == [("emit_checkpoint__artifact_ready", {"path": "result.txt"})]


@pytest.mark.asyncio
async def test_tenant_run_handles_cancellation(tmp_path: Path):
    c = _contract()

    class HangingSession:
        async def run(self, sub_prompt, on_checkpoint):
            await asyncio.sleep(10)

    def factory(**kwargs):
        return HangingSession()

    async def handler(name, args):
        from landlord.tenant import CheckpointVerdict
        return CheckpointVerdict(passed=True, reason="ok")

    runner = TenantRunner(
        contract=c,
        work_dir=tmp_path,
        checkpoint_handler=handler,
        sdk_session_factory=factory,
        model="claude-sonnet-4-6",
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    task.cancel()
    result = await task
    assert result.status == "evicted"
    assert result.reason == "cancelled"
```

- [ ] **Step 5.6: Run — all tenant tests pass**

Run:
```bash
pytest tests/test_tenant.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5.7: Commit**

```bash
git add landlord/tenant.py tests/test_tenant.py
git commit -m "$(cat <<'EOF'
feat: add TenantRunner with checkpoint tool routing

Pure helpers (sanitize_tool_name, checkpoint_tool_name, build_system_prompt)
are directly testable. TenantRunner.run takes a sdk_session_factory
injection seam so tests can substitute a fake SDK session; production
wires in the real ClaudeSDKClient. Checkpoint tool calls route through a
caller-supplied handler that returns a CheckpointVerdict.

EOF
)"
```

---

## Task 6: `orchestrator.py` — Landlord class (decompose, launch, evict, retry)

The orchestrator:
1. Decomposes a prompt into Contracts via `AnthropicClient.call_forced_tool` (forced decomposition tool).
2. Validates the plan (cycle-free DAG).
3. On approval, launches tenants concurrently with topo-ordered `asyncio.Event` gates.
4. Routes each tenant's checkpoint tool call through `Validator` and manages eviction + retry with clean-slate retry contracts.
5. Writes shared artifacts to disk and updates job state.

**Files:**
- Create: `landlord/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 6.1: Write the failing test — plan cycle detection**

Create `tests/test_orchestrator.py`:

```python
"""Tests for the Landlord orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.jobs import JobRegistry
from landlord.orchestrator import (
    DependencyCycleError,
    Landlord,
    resolve_launch_order,
)


def _c(role: str, depends_on: list[str] | None = None) -> Contract:
    return Contract(
        role=role,
        objective=f"obj {role}",
        sub_prompt=f"do {role}",
        checkpoints=[Checkpoint(
            name="done",
            description="done",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        )],
        output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        depends_on=depends_on or [],
    )


def test_resolve_launch_order_topological():
    plan = [
        _c("b", depends_on=["a"]),
        _c("a"),
        _c("c", depends_on=["b"]),
    ]
    ordered = resolve_launch_order(plan)
    roles = [c.role for c in ordered]
    assert roles.index("a") < roles.index("b") < roles.index("c")


def test_resolve_launch_order_detects_cycle():
    plan = [
        _c("a", depends_on=["b"]),
        _c("b", depends_on=["a"]),
    ]
    with pytest.raises(DependencyCycleError):
        resolve_launch_order(plan)


def test_resolve_launch_order_detects_self_dependency():
    plan = [_c("a", depends_on=["a"])]
    with pytest.raises(DependencyCycleError):
        resolve_launch_order(plan)
```

- [ ] **Step 6.2: Run — verify failure**

Run:
```bash
pytest tests/test_orchestrator.py -v
```
Expected: FAIL with `ImportError` for `landlord.orchestrator`.

- [ ] **Step 6.3: Write minimal `orchestrator.py` with topo/cycle logic**

Create `landlord/orchestrator.py`:

```python
"""Landlord orchestrator — decomposes prompts, launches tenants, handles eviction."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from landlord.anthropic_client import AnthropicClient, CachedBlock
from landlord.contract import Checkpoint, Contract
from landlord.jobs import Job, JobRegistry, TenantState
from landlord.tenant import CheckpointVerdict, TenantRunner
from landlord.validator import Validator


class DependencyCycleError(ValueError):
    """Raised when a plan's depends_on graph contains a cycle."""


def resolve_launch_order(plan: list[Contract]) -> list[Contract]:
    """Topologically sort contracts by depends_on. Raises on cycles."""
    by_role: dict[str, Contract] = {c.role: c for c in plan}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {c.role: WHITE for c in plan}
    order: list[Contract] = []

    def visit(role: str, stack: list[str]) -> None:
        if color.get(role) == GRAY:
            cycle = " -> ".join(stack + [role])
            raise DependencyCycleError(f"Dependency cycle: {cycle}")
        if color.get(role) == BLACK:
            return
        if role not in by_role:
            return
        color[role] = GRAY
        for dep in by_role[role].depends_on:
            visit(dep, stack + [role])
        color[role] = BLACK
        order.append(by_role[role])

    for c in plan:
        visit(c.role, [])
    return order


DECOMPOSE_SYSTEM = (
    "You are the Landlord, an agentic orchestrator. Given a user request, decompose it "
    "into independent sub-tasks that can be executed by isolated worker agents (tenants) "
    "in parallel where possible. For each tenant, return a contract with: role (short "
    "name), objective, sub_prompt (what the tenant receives), checkpoints (list of "
    "{name, description, schema} — schemas MUST be lenient JSON Schemas with a required "
    "property; no enum/const/pattern/minItems), output_schema, and depends_on (list of "
    "roles whose checkpoints this tenant needs before it can start). Keep the plan as "
    "small as it can reasonably be; avoid over-decomposition. Call the `emit_plan` tool "
    "with the contracts array."
)

DECOMPOSE_TOOL: dict[str, Any] = {
    "name": "emit_plan",
    "description": "Return the decomposed plan as a list of Contract objects.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contracts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "objective": {"type": "string"},
                        "sub_prompt": {"type": "string"},
                        "checkpoints": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "schema": {"type": "object"},
                                },
                                "required": ["name", "description", "schema"],
                            },
                        },
                        "output_schema": {"type": "object"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["role", "objective", "sub_prompt", "checkpoints", "output_schema"],
                },
            }
        },
        "required": ["contracts"],
    },
}


@dataclass
class OrchestratorConfig:
    landlord_model: str = "claude-opus-4-7"
    tenant_model: str = "claude-sonnet-4-6"
    default_max_retries: int = 3

    @classmethod
    def from_env(cls) -> OrchestratorConfig:
        return cls(
            landlord_model=os.environ.get("LANDLORD_LANDLORD_MODEL", "claude-opus-4-7"),
            tenant_model=os.environ.get("LANDLORD_TENANT_MODEL", "claude-sonnet-4-6"),
            default_max_retries=int(os.environ.get("LANDLORD_MAX_RETRIES", "3")),
        )


class Landlord:
    def __init__(
        self,
        config: OrchestratorConfig,
        registry: JobRegistry,
        client: AnthropicClient,
        validator: Validator,
        sdk_session_factory: Callable[..., Any],
    ) -> None:
        self._config = config
        self._registry = registry
        self._client = client
        self._validator = validator
        self._sdk_factory = sdk_session_factory

    async def decompose(self, prompt: str) -> list[Contract]:
        verdict = await self._client.call_forced_tool(
            system=[CachedBlock(text=DECOMPOSE_SYSTEM, cache=True)],
            messages=[{"role": "user", "content": prompt}],
            tool=DECOMPOSE_TOOL,
        )
        raw_contracts = verdict.get("contracts", [])
        contracts: list[Contract] = []
        for raw in raw_contracts:
            raw.setdefault("depends_on", [])
            raw.setdefault("max_retries", self._config.default_max_retries)
            contracts.append(Contract(**raw))
        # Cycle check up front — fail fast on bad decompositions.
        resolve_launch_order(contracts)
        return contracts

    async def launch(self, job: Job) -> None:
        """Spawn all tenant tasks. Returns immediately; tasks run in background."""
        dep_events: dict[str, asyncio.Event] = {c.role: asyncio.Event() for c in job.plan}
        order = resolve_launch_order(job.plan)
        for contract in order:
            tenant_state = job.tenants[contract.tenant_id]
            task = asyncio.create_task(self._run_tenant(job, tenant_state, dep_events))
            tenant_state.task = task

    async def wait_until_done(self, job: Job) -> None:
        tasks = [t.task for t in job.tenants.values() if t.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        all_complete = all(t.status == "complete" for t in job.tenants.values())
        new_status = "complete" if all_complete else "partial"
        await self._registry.transition(job.job_id, new_status)

    async def _run_tenant(
        self,
        job: Job,
        tenant_state: TenantState,
        dep_events: dict[str, asyncio.Event],
    ) -> None:
        contract = tenant_state.contract
        # Wait for every dependency to have passed at least one checkpoint.
        for dep_role in contract.depends_on:
            if dep_role in dep_events:
                await dep_events[dep_role].wait()

        shared_context = self._build_shared_context(job, contract)
        retry_context: str | None = tenant_state.last_error

        work_dir = job.output_dir / contract.tenant_id
        work_dir.mkdir(parents=True, exist_ok=True)

        tenant_state.status = "running"
        job.write_sidecar()

        async def checkpoint_handler(cp_name: str, args: dict[str, Any]) -> CheckpointVerdict:
            checkpoint = next(
                (cp for cp in contract.checkpoints if cp.name == cp_name),
                None,
            )
            if checkpoint is None:
                reason = f"Unknown checkpoint {cp_name}"
                tenant_state.last_error = reason
                return CheckpointVerdict(passed=False, reason=reason)
            result = await self._validator.validate_checkpoint(
                output=args, checkpoint=checkpoint, contract=contract
            )
            if result.passed:
                tenant_state.checkpoints_passed.append(cp_name)
                job.artifacts[contract.role] = args
                # Write shared-artifact file so downstream tenants can cat it.
                shared_path = job.output_dir / "shared" / f"{contract.role}.json"
                shared_path.write_text(json.dumps(args, indent=2, default=str))
                dep_events[contract.role].set()
                job.write_sidecar()
                return CheckpointVerdict(passed=True, reason=result.explanation)
            # Record the most recent failure so retries get fresh retry_context.
            tenant_state.last_error = f"Checkpoint '{cp_name}' failed: {result.explanation}"
            return CheckpointVerdict(passed=False, reason=result.explanation)

        runner = TenantRunner(
            contract=contract,
            work_dir=work_dir,
            checkpoint_handler=checkpoint_handler,
            sdk_session_factory=self._sdk_factory,
            model=self._config.tenant_model,
            shared_context=shared_context,
            retry_context=retry_context,
        )

        try:
            tenant_result = await runner.run()
        except Exception as e:
            tenant_state.status = "evicted"
            tenant_state.last_error = f"unexpected error: {e}"
            await self._maybe_retry(job, tenant_state, dep_events)
            return

        # If tenant finished without passing all required checkpoints, or explicitly was
        # evicted via a failed checkpoint verdict, decide whether to retry.
        required_checkpoint_names = {cp.name for cp in contract.checkpoints}
        passed = set(tenant_state.checkpoints_passed)
        if required_checkpoint_names - passed:
            tenant_state.status = "evicted"
            if tenant_state.last_error is None:
                tenant_state.last_error = "tenant finished without passing all checkpoints"
            await self._maybe_retry(job, tenant_state, dep_events)
            return

        tenant_state.status = "complete"
        job.write_sidecar()

    async def _maybe_retry(
        self,
        job: Job,
        tenant_state: TenantState,
        dep_events: dict[str, asyncio.Event],
    ) -> None:
        tenant_state.retry_count += 1
        if tenant_state.retry_count >= tenant_state.contract.max_retries:
            tenant_state.status = "escalated"
            job.write_sidecar()
            return
        # Clean-slate retry: clear checkpoints_passed but keep last_error as context.
        tenant_state.checkpoints_passed = []
        tenant_state.status = "pending"
        job.write_sidecar()
        task = asyncio.create_task(self._run_tenant(job, tenant_state, dep_events))
        tenant_state.task = task

    def _build_shared_context(self, job: Job, contract: Contract) -> str | None:
        if not contract.depends_on:
            return None
        parts = []
        for dep_role in contract.depends_on:
            if dep_role in job.artifacts:
                parts.append(
                    f"## {dep_role}\n"
                    f"Artifact also available at shared/{dep_role}.json\n"
                    f"{json.dumps(job.artifacts[dep_role], indent=2, default=str)}"
                )
        if not parts:
            return None
        return "Artifacts from dependencies:\n\n" + "\n\n".join(parts)
```

- [ ] **Step 6.4: Run — cycle + topo tests pass**

Run:
```bash
pytest tests/test_orchestrator.py::test_resolve_launch_order_topological tests/test_orchestrator.py::test_resolve_launch_order_detects_cycle tests/test_orchestrator.py::test_resolve_launch_order_detects_self_dependency -v
```
Expected: 3 tests pass.

- [ ] **Step 6.5: Add `decompose` test**

Append to `tests/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_decompose_parses_plan_from_forced_tool():
    mock_client = MagicMock()
    mock_client.call_forced_tool = AsyncMock(return_value={
        "contracts": [
            {
                "role": "backend",
                "objective": "build the api",
                "sub_prompt": "write an API",
                "checkpoints": [{
                    "name": "routes",
                    "description": "routes defined",
                    "schema": {"type": "object", "properties": {"routes": {"type": "array"}}, "required": ["routes"]},
                }],
                "output_schema": {"type": "object", "properties": {"routes": {"type": "array"}}, "required": ["routes"]},
                "depends_on": [],
            },
            {
                "role": "frontend",
                "objective": "build the ui",
                "sub_prompt": "write a UI",
                "checkpoints": [{
                    "name": "ui",
                    "description": "UI ready",
                    "schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                }],
                "output_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                "depends_on": ["backend"],
            },
        ]
    })

    from landlord.orchestrator import Landlord, OrchestratorConfig
    from landlord.validator import Validator

    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=JobRegistry(),
        client=mock_client,
        validator=MagicMock(spec=Validator),
        sdk_session_factory=lambda **kw: MagicMock(),
    )
    plan = await landlord.decompose("build a todo app")
    assert [c.role for c in plan] == ["backend", "frontend"]
    assert plan[1].depends_on == ["backend"]
    assert plan[0].max_retries == 3  # default


@pytest.mark.asyncio
async def test_decompose_raises_on_cycle():
    mock_client = MagicMock()
    mock_client.call_forced_tool = AsyncMock(return_value={
        "contracts": [
            {
                "role": "a",
                "objective": "o",
                "sub_prompt": "p",
                "checkpoints": [{"name": "x", "description": "d", "schema": {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]}}],
                "output_schema": {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]},
                "depends_on": ["b"],
            },
            {
                "role": "b",
                "objective": "o",
                "sub_prompt": "p",
                "checkpoints": [{"name": "x", "description": "d", "schema": {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]}}],
                "output_schema": {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]},
                "depends_on": ["a"],
            },
        ]
    })
    from landlord.orchestrator import DependencyCycleError, Landlord, OrchestratorConfig
    from landlord.validator import Validator

    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=JobRegistry(),
        client=mock_client,
        validator=MagicMock(spec=Validator),
        sdk_session_factory=lambda **kw: MagicMock(),
    )
    with pytest.raises(DependencyCycleError):
        await landlord.decompose("bad prompt")
```

- [ ] **Step 6.6: Run — decompose tests pass**

Run:
```bash
pytest tests/test_orchestrator.py -v
```
Expected: 5 tests pass.

- [ ] **Step 6.7: Add launch + dependency ordering + eviction tests**

Append to `tests/test_orchestrator.py`:

```python
class FakeSession:
    """Fake SDK session that emits scripted checkpoint tool calls."""
    def __init__(self, script: list[tuple[str, dict]], delay: float = 0):
        self.script = script
        self.delay = delay

    async def run(self, sub_prompt, on_checkpoint):
        if self.delay:
            await asyncio.sleep(self.delay)
        for tool_name, args in self.script:
            result = await on_checkpoint(tool_name, args)
            if not result.get("ok"):
                return


def make_factory(sessions_by_role: dict[str, FakeSession]):
    def factory(system_prompt, checkpoint_tools, work_dir, model):
        # Find role by matching the opening of system_prompt.
        for role, session in sessions_by_role.items():
            if f"You are a {role}" in system_prompt:
                return session
        raise AssertionError(f"No session for prompt: {system_prompt[:80]}")
    return factory


@pytest.mark.asyncio
async def test_launch_respects_dependency_order(tmp_path: Path):
    from landlord.orchestrator import Landlord, OrchestratorConfig
    from landlord.validator import Validator, ValidationResult

    mock_validator = MagicMock(spec=Validator)
    mock_validator.validate_checkpoint = AsyncMock(return_value=ValidationResult(
        passed=True, tier=2, explanation="ok"
    ))

    # backend emits instantly; frontend should wait until backend's checkpoint passes.
    backend_session = FakeSession([
        ("emit_checkpoint__done", {"x": "backend-artifact"}),
    ])
    frontend_session = FakeSession([
        ("emit_checkpoint__done", {"x": "frontend-artifact"}),
    ])
    factory = make_factory({"backend": backend_session, "frontend": frontend_session})

    registry = JobRegistry()
    plan = [
        _c("frontend", depends_on=["backend"]),
        _c("backend"),
    ]
    job = await registry.create_job(prompt="p", plan=plan, output_dir=tmp_path)

    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=registry,
        client=MagicMock(),
        validator=mock_validator,
        sdk_session_factory=factory,
    )
    await registry.transition(job.job_id, "running")
    await landlord.launch(job)
    await landlord.wait_until_done(job)

    assert job.status == "complete"
    assert job.artifacts["backend"] == {"x": "backend-artifact"}
    assert job.artifacts["frontend"] == {"x": "frontend-artifact"}
    frontend_state = next(t for t in job.tenants.values() if t.contract.role == "frontend")
    assert "backend" in (frontend_state.contract.depends_on)
    shared_file = job.output_dir / "shared" / "backend.json"
    assert shared_file.exists()
    assert json.loads(shared_file.read_text()) == {"x": "backend-artifact"}


@pytest.mark.asyncio
async def test_eviction_retries_and_escalates(tmp_path: Path):
    from landlord.orchestrator import Landlord, OrchestratorConfig
    from landlord.validator import Validator, ValidationResult

    mock_validator = MagicMock(spec=Validator)
    mock_validator.validate_checkpoint = AsyncMock(return_value=ValidationResult(
        passed=False, tier=2, explanation="off topic"
    ))

    # Session always emits an invalid checkpoint.
    session_script = [("emit_checkpoint__done", {"x": "bad"})]
    role_counter = {"worker": 0}

    def factory(system_prompt, checkpoint_tools, work_dir, model):
        role_counter["worker"] += 1
        return FakeSession(script=list(session_script))

    registry = JobRegistry()
    plan = [_c("worker")]
    plan[0] = plan[0].model_copy(update={"max_retries": 2})
    job = await registry.create_job(prompt="p", plan=plan, output_dir=tmp_path)

    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=registry,
        client=MagicMock(),
        validator=mock_validator,
        sdk_session_factory=factory,
    )
    await registry.transition(job.job_id, "running")
    await landlord.launch(job)
    await landlord.wait_until_done(job)

    worker_state = next(iter(job.tenants.values()))
    assert worker_state.status == "escalated"
    assert worker_state.retry_count == 2
    assert role_counter["worker"] == 2  # 1 initial + 1 retry before escalation
    assert job.status == "partial"


@pytest.mark.asyncio
async def test_successful_retry_passes_after_failure(tmp_path: Path):
    from landlord.orchestrator import Landlord, OrchestratorConfig
    from landlord.validator import Validator, ValidationResult

    # First call fails, subsequent calls pass.
    call_count = {"n": 0}

    async def flaky_validate(output, checkpoint, contract):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ValidationResult(passed=False, tier=2, explanation="first fail")
        return ValidationResult(passed=True, tier=2, explanation="ok")

    mock_validator = MagicMock(spec=Validator)
    mock_validator.validate_checkpoint = flaky_validate

    def factory(system_prompt, checkpoint_tools, work_dir, model):
        return FakeSession([("emit_checkpoint__done", {"x": "try"})])

    registry = JobRegistry()
    plan = [_c("worker")]
    job = await registry.create_job(prompt="p", plan=plan, output_dir=tmp_path)

    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=registry,
        client=MagicMock(),
        validator=mock_validator,
        sdk_session_factory=factory,
    )
    await registry.transition(job.job_id, "running")
    await landlord.launch(job)
    await landlord.wait_until_done(job)

    worker_state = next(iter(job.tenants.values()))
    assert worker_state.status == "complete"
    assert worker_state.retry_count == 1
    assert job.status == "complete"
    assert job.artifacts["worker"] == {"x": "try"}
```

- [ ] **Step 6.8: Run — all orchestrator tests pass**

Run:
```bash
pytest tests/test_orchestrator.py -v
```
Expected: 8 tests pass.

- [ ] **Step 6.9: Commit**

```bash
git add landlord/orchestrator.py tests/test_orchestrator.py
git commit -m "$(cat <<'EOF'
feat: add Landlord orchestrator with decompose, launch, evict, retry

decompose() uses AnthropicClient.call_forced_tool with the emit_plan tool
to force a well-formed contracts array. launch() runs tenants concurrently
with asyncio.Event gates for depends_on ordering. Checkpoint tool calls
route through Validator; failed checkpoints trigger clean-slate retries
up to max_retries, then escalate. Shared artifacts written to job/shared/
and injected into dependent tenant system prompts.

EOF
)"
```

---

## Task 7: `mcp_server.py` — the 5 MCP tools

Wire the orchestrator behind five MCP tool handlers. Bootstrap the MCP server and register the Anthropic SDK session factory that adapts `claude_agent_sdk.ClaudeSDKClient` to the `TenantRunner.sdk_session_factory` protocol.

**Files:**
- Create: `landlord/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 7.1: Write the failing test — `start_orchestration` returns plan**

Create `tests/test_mcp_server.py`:

```python
"""Tests for the MCP server tool handlers.

These tests exercise the in-process tool handlers without actually starting the MCP
stdio server. The handlers are pure functions over the LandlordServer instance.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.mcp_server import LandlordServer
from landlord.orchestrator import Landlord, OrchestratorConfig


def _c(role: str, depends_on: list[str] | None = None) -> Contract:
    return Contract(
        role=role,
        objective=f"obj {role}",
        sub_prompt=f"do {role}",
        checkpoints=[Checkpoint(
            name="done",
            description="done",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        )],
        output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        depends_on=depends_on or [],
    )


@pytest.fixture
def server(tmp_path: Path):
    mock_landlord = MagicMock(spec=Landlord)
    s = LandlordServer(
        config=OrchestratorConfig(),
        landlord=mock_landlord,
        default_output_dir=tmp_path,
    )
    s._mock_landlord = mock_landlord  # expose for tests
    return s


@pytest.mark.asyncio
async def test_start_orchestration_returns_plan_and_job_id(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("writer")])

    result = await server.start_orchestration(prompt="draft an essay")

    assert result["status"] == "awaiting_approval"
    assert "job_id" in result
    assert len(result["plan"]) == 1
    assert result["plan"][0]["role"] == "writer"
    server._mock_landlord.decompose.assert_awaited_once_with("draft an essay")
```

- [ ] **Step 7.2: Run — verify failure**

Run:
```bash
pytest tests/test_mcp_server.py::test_start_orchestration_returns_plan_and_job_id -v
```
Expected: FAIL with `ImportError` for `landlord.mcp_server`.

- [ ] **Step 7.3: Write minimal `mcp_server.py` with `LandlordServer` class**

Create `landlord/mcp_server.py`:

```python
"""MCP server exposing Landlord orchestration as five async tools."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from landlord.anthropic_client import AnthropicClient
from landlord.contract import Contract
from landlord.jobs import Job, JobRegistry
from landlord.orchestrator import (
    DependencyCycleError,
    Landlord,
    OrchestratorConfig,
    resolve_launch_order,
)
from landlord.validator import Validator


class LandlordServer:
    """Holds the shared state and implements the five MCP tool handlers."""

    def __init__(
        self,
        config: OrchestratorConfig,
        landlord: Landlord,
        default_output_dir: Path,
    ) -> None:
        self._config = config
        self._landlord = landlord
        self._registry: JobRegistry = getattr(landlord, "_registry", None) or JobRegistry()
        self._default_output_dir = default_output_dir

    def _resolve_output_dir(self, output_dir: str | None) -> Path:
        if output_dir is None:
            return self._default_output_dir
        p = Path(output_dir)
        return p if p.is_absolute() else (Path.cwd() / p).resolve()

    async def start_orchestration(
        self,
        prompt: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        resolved_dir = self._resolve_output_dir(output_dir)
        resolved_dir.mkdir(parents=True, exist_ok=True)
        plan = await self._landlord.decompose(prompt)
        job = await self._registry.create_job(prompt=prompt, plan=plan, output_dir=resolved_dir)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "plan": [c.model_dump() for c in job.plan],
        }

    async def approve_plan(
        self,
        job_id: str,
        edits: list[dict] | None = None,
    ) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status != "awaiting_approval":
            raise ValueError(f"Job {job_id} is not awaiting approval (status={job.status})")

        if edits is not None:
            try:
                new_plan = [Contract(**raw) for raw in edits]
            except Exception as e:
                raise ValueError(f"Invalid edited plan: {e}") from e
            try:
                resolve_launch_order(new_plan)
            except DependencyCycleError as e:
                raise ValueError(f"Edited plan has a dependency cycle: {e}") from e
            job = await self._registry.replace_plan(job_id, new_plan)

        await self._registry.transition(job_id, "running")
        # Launch without awaiting completion — tool returns immediately.
        await self._landlord.launch(job)
        # Start a background waiter to transition to complete/partial when tenants finish.
        asyncio.create_task(self._landlord.wait_until_done(job))
        return {"job_id": job_id, "status": "running"}

    async def get_status(self, job_id: str) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        return {
            "job_id": job.job_id,
            "status": job.status,
            "plan": [c.model_dump() for c in job.plan],
            "tenants": [t.to_dict() for t in job.tenants.values()],
        }

    async def get_artifacts(self, job_id: str) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status not in ("complete", "partial", "cancelled"):
            raise ValueError(
                f"Artifacts not available for job {job_id} (status={job.status}); "
                f"valid statuses: complete, partial, cancelled"
            )
        files: dict[str, list[str]] = {}
        for tenant_state in job.tenants.values():
            role = tenant_state.contract.role
            tenant_dir = job.output_dir / tenant_state.contract.tenant_id
            if tenant_dir.exists():
                files[role] = sorted(
                    str(p.relative_to(job.output_dir)).replace("\\", "/")
                    for p in tenant_dir.rglob("*") if p.is_file()
                )
            else:
                files[role] = []
        return {
            "job_id": job.job_id,
            "status": job.status,
            "artifacts": dict(job.artifacts),
            "files": files,
        }

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = await self._registry.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        if job.status not in ("awaiting_approval", "running"):
            raise ValueError(f"Cannot cancel job {job_id} (status={job.status})")
        for tenant_state in job.tenants.values():
            if tenant_state.task is not None and not tenant_state.task.done():
                tenant_state.task.cancel()
        await self._registry.transition(job_id, "cancelled")
        return {"job_id": job_id, "status": "cancelled"}


def _build_sdk_session_factory() -> Any:
    """Build the production SDK session factory.

    Importing claude_agent_sdk is deferred so the test suite can run without it
    installed. The factory adapter maps TenantRunner's interface to the real SDK.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server, tool

    def factory(system_prompt, checkpoint_tools, work_dir, model):
        return _SDKSessionAdapter(
            system_prompt=system_prompt,
            checkpoint_tools=checkpoint_tools,
            work_dir=work_dir,
            model=model,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ClaudeSDKClient=ClaudeSDKClient,
            create_sdk_mcp_server=create_sdk_mcp_server,
            tool=tool,
        )
    return factory


class _SDKSessionAdapter:
    """Adapts ClaudeSDKClient to TenantRunner's `run(sub_prompt, on_checkpoint)` protocol.

    Registers each checkpoint tool as an in-process SDK MCP tool whose handler calls
    the `on_checkpoint` callback supplied by TenantRunner.
    """
    def __init__(
        self,
        system_prompt,
        checkpoint_tools,
        work_dir,
        model,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        create_sdk_mcp_server,
        tool,
    ):
        self._system_prompt = system_prompt
        self._checkpoint_tools = checkpoint_tools
        self._work_dir = work_dir
        self._model = model
        self._ClaudeAgentOptions = ClaudeAgentOptions
        self._ClaudeSDKClient = ClaudeSDKClient
        self._create_sdk_mcp_server = create_sdk_mcp_server
        self._tool = tool

    async def run(self, sub_prompt, on_checkpoint):
        # Build SDK tools that forward calls to on_checkpoint.
        sdk_tools = []
        for t in self._checkpoint_tools:
            # Each SDK tool closes over the target checkpoint name.
            tool_name = t["name"]
            input_schema = t["input_schema"]

            async def handler(args, _tool_name=tool_name):
                result = await on_checkpoint(_tool_name, args)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            sdk_tools.append(self._tool(tool_name, t["description"], input_schema)(handler))

        mcp_server = self._create_sdk_mcp_server(
            name="landlord_checkpoints", version="1.0.0", tools=sdk_tools
        )
        options = self._ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            cwd=str(self._work_dir),
            model=self._model,
            mcp_servers={"checkpoints": mcp_server},
        )
        async with self._ClaudeSDKClient(options=options) as client:
            await client.query(sub_prompt)
            async for _message in client.receive_response():
                pass  # SDK raises on error; we let it propagate.


def build_default_server() -> LandlordServer:
    """Wire a production LandlordServer from environment configuration."""
    config = OrchestratorConfig.from_env()
    default_output = Path(os.environ.get("LANDLORD_OUTPUT_DIR", "./landlord-output")).resolve()
    default_output.mkdir(parents=True, exist_ok=True)
    client = AnthropicClient(model=config.landlord_model)
    validator = Validator(client=client)
    registry = JobRegistry()
    landlord = Landlord(
        config=config,
        registry=registry,
        client=client,
        validator=validator,
        sdk_session_factory=_build_sdk_session_factory(),
    )
    return LandlordServer(config=config, landlord=landlord, default_output_dir=default_output)


def main() -> None:
    """Entry point for the `landlord-mcp` console script. Runs the stdio server."""
    from mcp.server.fastmcp import FastMCP

    server = build_default_server()
    mcp = FastMCP("landlord")

    @mcp.tool()
    async def start_orchestration(prompt: str, output_dir: str | None = None) -> dict:
        """Decompose the prompt into a plan and return job_id + plan awaiting approval."""
        return await server.start_orchestration(prompt=prompt, output_dir=output_dir)

    @mcp.tool()
    async def approve_plan(job_id: str, edits: list[dict] | None = None) -> dict:
        """Approve (or replace via edits) the plan for job_id and launch tenants."""
        return await server.approve_plan(job_id=job_id, edits=edits)

    @mcp.tool()
    async def get_status(job_id: str) -> dict:
        """Return current status, plan, and per-tenant states for job_id."""
        return await server.get_status(job_id=job_id)

    @mcp.tool()
    async def get_artifacts(job_id: str) -> dict:
        """Return final artifacts and file lists; requires job to be done or cancelled."""
        return await server.get_artifacts(job_id=job_id)

    @mcp.tool()
    async def cancel(job_id: str) -> dict:
        """Cancel a running or pending job."""
        return await server.cancel(job_id=job_id)

    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.4: Rewrite tests to not depend on `Landlord` attribute name**

The test from Step 7.1 references `server._mock_landlord`. That's fine because the fixture sets it. However the server constructor calls `getattr(landlord, "_registry", None)` which on a MagicMock returns a MagicMock — we need the test to handle this. Update `LandlordServer.__init__` to accept an explicit `registry` parameter, then update the test fixture.

Modify `landlord/mcp_server.py` — replace the `__init__` signature and body of `LandlordServer`:

```python
    def __init__(
        self,
        config: OrchestratorConfig,
        landlord: Landlord,
        default_output_dir: Path,
        registry: JobRegistry | None = None,
    ) -> None:
        self._config = config
        self._landlord = landlord
        self._registry = registry if registry is not None else getattr(landlord, "_registry", None) or JobRegistry()
        self._default_output_dir = default_output_dir
```

And update `build_default_server` to pass `registry=registry` when constructing `LandlordServer`:

```python
    return LandlordServer(
        config=config,
        landlord=landlord,
        default_output_dir=default_output,
        registry=registry,
    )
```

Update the test fixture to pass an explicit registry:

Replace the `server` fixture in `tests/test_mcp_server.py`:

```python
@pytest.fixture
def server(tmp_path: Path):
    from landlord.jobs import JobRegistry
    mock_landlord = MagicMock(spec=Landlord)
    registry = JobRegistry()
    s = LandlordServer(
        config=OrchestratorConfig(),
        landlord=mock_landlord,
        default_output_dir=tmp_path,
        registry=registry,
    )
    s._mock_landlord = mock_landlord
    return s
```

- [ ] **Step 7.5: Run — first test passes**

Run:
```bash
pytest tests/test_mcp_server.py::test_start_orchestration_returns_plan_and_job_id -v
```
Expected: PASS.

- [ ] **Step 7.6: Add approve_plan, status, artifacts, cancel tests**

Append to `tests/test_mcp_server.py`:

```python
@pytest.mark.asyncio
async def test_approve_plan_rejects_unknown_job(server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await server.approve_plan(job_id="does-not-exist")


@pytest.mark.asyncio
async def test_approve_plan_rejects_wrong_status(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("w")])
    server._mock_landlord.launch = AsyncMock()
    server._mock_landlord.wait_until_done = AsyncMock()
    started = await server.start_orchestration(prompt="p")
    await server.approve_plan(job_id=started["job_id"])
    # Second approve should fail because status is now "running".
    with pytest.raises(ValueError, match="not awaiting approval"):
        await server.approve_plan(job_id=started["job_id"])


@pytest.mark.asyncio
async def test_approve_plan_with_valid_edits_replaces_plan(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("w")])
    server._mock_landlord.launch = AsyncMock()
    server._mock_landlord.wait_until_done = AsyncMock()
    started = await server.start_orchestration(prompt="p")
    edits = [_c("replacement").model_dump()]
    result = await server.approve_plan(job_id=started["job_id"], edits=edits)
    assert result["status"] == "running"

    job = await server._registry.get(started["job_id"])
    assert job is not None
    assert job.plan[0].role == "replacement"


@pytest.mark.asyncio
async def test_approve_plan_rejects_edits_with_cycle(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("w")])
    started = await server.start_orchestration(prompt="p")
    cyclic_edits = [
        _c("x", depends_on=["y"]).model_dump(),
        _c("y", depends_on=["x"]).model_dump(),
    ]
    with pytest.raises(ValueError, match="cycle"):
        await server.approve_plan(job_id=started["job_id"], edits=cyclic_edits)


@pytest.mark.asyncio
async def test_get_status_returns_tenant_list(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    started = await server.start_orchestration(prompt="p")
    status = await server.get_status(job_id=started["job_id"])
    assert status["status"] == "awaiting_approval"
    assert len(status["tenants"]) == 1
    assert status["tenants"][0]["role"] == "worker"
    assert status["tenants"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_status_unknown_job_raises(server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await server.get_status(job_id="ghost")


@pytest.mark.asyncio
async def test_get_artifacts_requires_terminal_status(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    started = await server.start_orchestration(prompt="p")
    with pytest.raises(ValueError, match="Artifacts not available"):
        await server.get_artifacts(job_id=started["job_id"])


@pytest.mark.asyncio
async def test_get_artifacts_returns_after_completion(server, tmp_path: Path):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    started = await server.start_orchestration(prompt="p")
    job = await server._registry.get(started["job_id"])
    assert job is not None

    tenant_state = next(iter(job.tenants.values()))
    job.artifacts["worker"] = {"x": "done"}
    tenant_dir = job.output_dir / tenant_state.contract.tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)
    (tenant_dir / "result.txt").write_text("hello")

    await server._registry.transition(started["job_id"], "complete")
    result = await server.get_artifacts(job_id=started["job_id"])
    assert result["artifacts"] == {"worker": {"x": "done"}}
    assert "worker" in result["files"]
    assert any("result.txt" in f for f in result["files"]["worker"])


@pytest.mark.asyncio
async def test_cancel_running_job(server):
    import asyncio
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    server._mock_landlord.launch = AsyncMock()
    server._mock_landlord.wait_until_done = AsyncMock()
    started = await server.start_orchestration(prompt="p")

    # Inject a fake running task into the tenant state.
    job = await server._registry.get(started["job_id"])
    assert job is not None

    async def hang():
        await asyncio.sleep(10)

    fake_task = asyncio.create_task(hang())
    next(iter(job.tenants.values())).task = fake_task

    await server._registry.transition(started["job_id"], "running")
    result = await server.cancel(job_id=started["job_id"])
    assert result["status"] == "cancelled"
    # Give cancellation a tick to propagate.
    await asyncio.sleep(0.01)
    assert fake_task.cancelled()


@pytest.mark.asyncio
async def test_cancel_rejects_terminal_status(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    started = await server.start_orchestration(prompt="p")
    await server._registry.transition(started["job_id"], "complete")
    with pytest.raises(ValueError, match="Cannot cancel"):
        await server.cancel(job_id=started["job_id"])
```

- [ ] **Step 7.7: Run — full MCP server suite passes**

Run:
```bash
pytest tests/test_mcp_server.py -v
```
Expected: 11 tests pass.

- [ ] **Step 7.8: Commit**

```bash
git add landlord/mcp_server.py tests/test_mcp_server.py
git commit -m "$(cat <<'EOF'
feat: add LandlordServer + FastMCP entry point

Five MCP tool handlers on LandlordServer: start_orchestration,
approve_plan (supports edits), get_status, get_artifacts, cancel.
Preconditions enforced with explicit ValueError messages.
_SDKSessionAdapter adapts claude_agent_sdk.ClaudeSDKClient to the
TenantRunner factory protocol; registered via an in-process SDK MCP
server that exposes per-checkpoint synthetic tools.
main() wires FastMCP and runs the stdio server.

EOF
)"
```

---

## Task 8: End-to-end smoke test with fully mocked dependencies

A single integration test that drives the server through start → approve → get_status → get_artifacts, with the Anthropic client and SDK session factory both mocked, verifying the full orchestration flow fits together.

**Files:**
- Test: `tests/test_e2e.py`

- [ ] **Step 8.1: Write the smoke test**

Create `tests/test_e2e.py`:

```python
"""End-to-end smoke test with mocked Anthropic + SDK."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.anthropic_client import AnthropicClient
from landlord.contract import Checkpoint, Contract
from landlord.jobs import JobRegistry
from landlord.mcp_server import LandlordServer
from landlord.orchestrator import Landlord, OrchestratorConfig
from landlord.validator import ValidationResult, Validator


class ScriptedSession:
    def __init__(self, role: str):
        self.role = role

    async def run(self, sub_prompt, on_checkpoint):
        await on_checkpoint("emit_checkpoint__done", {"x": f"{self.role}-artifact"})


@pytest.mark.asyncio
async def test_e2e_two_tenant_happy_path(tmp_path: Path):
    # Mock Anthropic client: decompose returns two tenants, judge always passes.
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.call_forced_tool = AsyncMock()
    call_log = []

    async def fake_call_forced_tool(system, messages, tool):
        call_log.append(tool["name"])
        if tool["name"] == "emit_plan":
            return {
                "contracts": [
                    {
                        "role": "backend",
                        "objective": "build api",
                        "sub_prompt": "make a server",
                        "checkpoints": [{
                            "name": "done",
                            "description": "api ready",
                            "schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
                        }],
                        "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
                        "depends_on": [],
                    },
                    {
                        "role": "frontend",
                        "objective": "build ui",
                        "sub_prompt": "make a ui",
                        "checkpoints": [{
                            "name": "done",
                            "description": "ui ready",
                            "schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
                        }],
                        "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
                        "depends_on": ["backend"],
                    },
                ]
            }
        if tool["name"] == "judge_checkpoint":
            return {"passed": True, "reason": "looks good"}
        raise AssertionError(f"unexpected tool: {tool['name']}")

    mock_client.call_forced_tool = fake_call_forced_tool

    def factory(system_prompt, checkpoint_tools, work_dir, model):
        for role in ("backend", "frontend"):
            if f"You are a {role}" in system_prompt:
                return ScriptedSession(role)
        raise AssertionError("no matching scripted session")

    registry = JobRegistry()
    config = OrchestratorConfig()
    validator = Validator(client=mock_client)
    landlord = Landlord(
        config=config,
        registry=registry,
        client=mock_client,
        validator=validator,
        sdk_session_factory=factory,
    )
    server = LandlordServer(
        config=config,
        landlord=landlord,
        default_output_dir=tmp_path,
        registry=registry,
    )

    started = await server.start_orchestration(prompt="build a todo app")
    assert started["status"] == "awaiting_approval"
    assert {c["role"] for c in started["plan"]} == {"backend", "frontend"}

    approved = await server.approve_plan(job_id=started["job_id"])
    assert approved["status"] == "running"

    # Wait for the background wait_until_done task to finish.
    job = await registry.get(started["job_id"])
    assert job is not None
    while job.status == "running":
        await asyncio.sleep(0.02)
        job = await registry.get(started["job_id"])

    status = await server.get_status(job_id=started["job_id"])
    assert status["status"] == "complete"
    assert {t["role"] for t in status["tenants"]} == {"backend", "frontend"}
    assert all(t["status"] == "complete" for t in status["tenants"])

    arts = await server.get_artifacts(job_id=started["job_id"])
    assert arts["artifacts"]["backend"] == {"x": "backend-artifact"}
    assert arts["artifacts"]["frontend"] == {"x": "frontend-artifact"}

    # call_log should include one emit_plan and at least two judge_checkpoint calls.
    assert call_log.count("emit_plan") == 1
    assert call_log.count("judge_checkpoint") >= 2

    # Shared-artifact file for backend must exist for frontend's dependency.
    shared_backend = job.output_dir / "shared" / "backend.json"
    assert shared_backend.exists()
```

- [ ] **Step 8.2: Run the smoke test**

Run:
```bash
pytest tests/test_e2e.py -v
```
Expected: 1 test passes.

- [ ] **Step 8.3: Run the full suite to catch regressions**

Run:
```bash
pytest -v
```
Expected: all tests pass (Task 1 kept `test_contract.py`; Tasks 2-7 added five files; Task 8 added `test_e2e.py`).

- [ ] **Step 8.4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "$(cat <<'EOF'
test: add end-to-end smoke covering start -> approve -> artifacts

Exercises the full orchestration flow with Anthropic client and SDK
session factory both mocked. Verifies dependency ordering, shared
artifact file creation, and that the forced tools (emit_plan,
judge_checkpoint) are invoked the expected number of times.

EOF
)"
```

---

## Task 9: README + `.claude/mcp.json` configuration docs

Wrap up with user-facing docs: how to install, configure, and register the MCP server with Claude Code. No test — docs only.

**Files:**
- Modify: `README.md` (create if missing)
- Create: `docs/usage.md`

- [ ] **Step 9.1: Check existing README**

Run:
```bash
ls README.md 2>&1
```
Note whether a README exists. If it does, extend it; if it doesn't, create it.

- [ ] **Step 9.2: Write/replace `README.md`**

Create (or replace) `README.md`:

```markdown
# Landlord Framework

Contract-based agent orchestration, exposed as an MCP server.

A calling LLM (Claude Code, Cursor, Cline, or any MCP client) can hand Landlord a
natural-language task; Landlord decomposes it into a plan of parallel tenant agents,
returns the plan for review, launches the tenants as concurrent Claude Agent SDK
sessions, validates their checkpoints, evicts and retries misbehaving tenants, and
returns the per-role artifacts.

## Install

```bash
pip install -e .
```

Set the required environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Run the MCP server

```bash
landlord-mcp
```

This speaks MCP over stdio. Normally you don't run it directly — you point an MCP
client at it. For Claude Code, add this to your `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "landlord": {
      "command": "landlord-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "LANDLORD_OUTPUT_DIR": "./landlord-output"
      }
    }
  }
}
```

Restart Claude Code; the five Landlord tools will be discoverable to the model.

## Tool surface

| Tool | Purpose |
|---|---|
| `start_orchestration(prompt, output_dir?)` | Decompose the prompt into a plan. Returns `job_id` and the plan awaiting approval. |
| `approve_plan(job_id, edits?)` | Approve (or replace with edits) the plan. Launches tenants. |
| `get_status(job_id)` | Poll overall status plus per-tenant state. |
| `get_artifacts(job_id)` | Retrieve final artifacts and file listings once the job is done/cancelled. |
| `cancel(job_id)` | Cancel a running or pending job. |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. |
| `LANDLORD_LANDLORD_MODEL` | `claude-opus-4-7` | Decomposition + judge model. |
| `LANDLORD_TENANT_MODEL` | `claude-sonnet-4-6` | Tenant SDK session model. |
| `LANDLORD_OUTPUT_DIR` | `./landlord-output` | Root directory for job outputs. |
| `LANDLORD_MAX_RETRIES` | `3` | Default max retries per tenant. |

## Legacy CLI

The old litellm-based CLI is preserved as `landlord`:

```bash
pip install -e ".[legacy]"
landlord "your task"
```

See `landlord/legacy/` for source.

## Development

```bash
pip install -e ".[dev]"
pytest
```
```

- [ ] **Step 9.3: Commit**

```bash
git add README.md
git commit -m "docs: document MCP server usage and .claude/mcp.json setup"
```

---

## Final Verification

- [ ] **Run the full test suite**

Run:
```bash
pytest -v
```
Expected: all tests in `tests/` pass; legacy tests under `tests/legacy/` are not collected.

- [ ] **Verify the entry point is importable**

Run:
```bash
python -c "from landlord.mcp_server import build_default_server, main, LandlordServer; print('OK')"
```
Expected: `OK`.

- [ ] **Verify `landlord-mcp` command is on PATH**

Run:
```bash
pip install -e .
which landlord-mcp || where landlord-mcp
```
Expected: prints the installed script path.

The server cannot be fully exercised without a valid `ANTHROPIC_API_KEY` and the
`claude-agent-sdk` installed — those are real-world smoke-test concerns beyond the
unit-test-driven scope of this plan.
