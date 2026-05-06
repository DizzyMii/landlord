"""Tests for the Claude Agent SDK-backed tenant runner."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.tenant import (
    CHECKPOINT_TOOL_PREFIX,
    CheckpointVerdict,
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
    def factory(system_prompt, checkpoint_tools, work_dir, model, **kwargs):
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
async def test_tenant_run_forwards_permission_callback_to_factory(tmp_path: Path):
    """When TenantRunner is given a permission_callback, the factory must
    receive it so the SDK adapter can wire it into can_use_tool."""
    captured = {}

    class _NullSession:
        async def run(self, sub_prompt, on_checkpoint):
            return

    def factory(system_prompt, checkpoint_tools, work_dir, model, **kwargs):
        captured.update(kwargs)
        return _NullSession()

    async def my_callback(role, tool_name, tool_input):
        return True

    runner = TenantRunner(
        contract=_contract(),
        work_dir=tmp_path,
        checkpoint_handler=lambda *_: None,  # never invoked since session does nothing
        sdk_session_factory=factory,
        model="claude-sonnet-4-6",
        permission_callback=my_callback,
    )
    await runner.run()
    assert captured.get("permission_callback") is my_callback
    assert captured.get("role") == "worker"


@pytest.mark.asyncio
async def test_tenant_run_passes_none_callback_when_not_supplied(tmp_path: Path):
    captured = {}

    class _NullSession:
        async def run(self, sub_prompt, on_checkpoint):
            return

    def factory(system_prompt, checkpoint_tools, work_dir, model, **kwargs):
        captured.update(kwargs)
        return _NullSession()

    runner = TenantRunner(
        contract=_contract(),
        work_dir=tmp_path,
        checkpoint_handler=lambda *_: None,
        sdk_session_factory=factory,
        model="claude-sonnet-4-6",
    )
    await runner.run()
    assert captured.get("permission_callback") is None


@pytest.mark.asyncio
async def test_tenant_run_handles_cancellation(tmp_path: Path):
    c = _contract()

    class HangingSession:
        async def run(self, sub_prompt, on_checkpoint):
            await asyncio.sleep(10)

    def factory(**kwargs):
        return HangingSession()

    async def handler(name, args):
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
