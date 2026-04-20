"""Tests for the Landlord orchestrator."""
from __future__ import annotations

import asyncio
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
    assert plan[0].max_retries == 3


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
    assert role_counter["worker"] == 2
    assert job.status == "partial"


@pytest.mark.asyncio
async def test_successful_retry_passes_after_failure(tmp_path: Path):
    from landlord.orchestrator import Landlord, OrchestratorConfig
    from landlord.validator import Validator, ValidationResult

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
