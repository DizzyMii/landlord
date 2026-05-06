"""E2E suite that validates each documented Landlord claim against actual behavior.

Each test maps to a specific README/docstring claim. The goal is to verify the
tool does *exactly* what it says — no more, no less. Tests use a scripted SDK
session factory so the orchestration runs end-to-end without hitting any model.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.agent_sdk_client import AgentSDKClient
from landlord.contract import Checkpoint, Contract
from landlord.jobs import JobRegistry
from landlord.mcp_server import (
    LandlordServer,
    _AUTO_APPROVE_PREFIXES,
    _AUTO_APPROVE_TOOLS,
    _SDKSessionAdapter,
    _format_event_message,
    _is_auto_approved,
    build_default_server,
)
from landlord.orchestrator import Landlord, OrchestratorConfig, resolve_launch_order
from landlord.validator import ValidationResult, Validator


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _checkpoint(name: str = "done") -> Checkpoint:
    return Checkpoint(
        name=name,
        description=f"checkpoint {name}",
        schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )


def _contract(role: str, depends_on: list[str] | None = None, max_retries: int = 3) -> Contract:
    return Contract(
        role=role,
        objective=f"objective for {role}",
        sub_prompt=f"do the {role} task",
        checkpoints=[_checkpoint()],
        output_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        depends_on=depends_on or [],
        max_retries=max_retries,
    )


class ScriptedSession:
    """A stand-in SDK session that emits a configurable list of checkpoint calls."""

    def __init__(self, role: str, calls: list[tuple[str, dict]] | None = None, delay: float = 0):
        self.role = role
        self.calls = calls or [("emit_checkpoint__done", {"x": f"{role}-artifact"})]
        self.delay = delay
        self.started_at: float | None = None
        self.finished_at: float | None = None

    async def run(self, sub_prompt, on_checkpoint):
        self.started_at = asyncio.get_event_loop().time()
        if self.delay:
            await asyncio.sleep(self.delay)
        for tool_name, args in self.calls:
            verdict = await on_checkpoint(tool_name, args)
            if not verdict.get("ok"):
                # Stop on a failed checkpoint so the orchestrator can decide eviction.
                break
        self.finished_at = asyncio.get_event_loop().time()


def _factory_for(sessions: dict[str, ScriptedSession]):
    """Build an SDK session factory that selects by role substring in the system prompt."""

    def factory(system_prompt, checkpoint_tools, work_dir, model, role=None, **kwargs):
        if role is not None and role in sessions:
            return sessions[role]
        for r, session in sessions.items():
            if f"You are a {r}" in system_prompt:
                return session
        raise AssertionError(f"No scripted session for role: {role!r} / prompt={system_prompt[:80]!r}")

    return factory


def _decomposer(plan: list[Contract]):
    """Build a mock AgentSDKClient whose `decompose` returns the given plan."""
    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        if tool["name"] == "emit_plan":
            return {"contracts": [c.model_dump() for c in plan]}
        if tool["name"] == "judge_checkpoint":
            return {"passed": True, "reason": "ok"}
        raise AssertionError(f"unexpected forced tool: {tool['name']}")

    client.call_forced_tool = fake
    return client


def _build_server(
    plan: list[Contract],
    sessions: dict[str, ScriptedSession],
    output_dir: Path,
    *,
    judge_passes: bool = True,
    judge_reason: str = "ok",
    config: OrchestratorConfig | None = None,
):
    """Wire a LandlordServer with a mock decomposer + scripted sessions."""
    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        if tool["name"] == "emit_plan":
            return {"contracts": [c.model_dump() for c in plan]}
        if tool["name"] == "judge_checkpoint":
            return {"passed": judge_passes, "reason": judge_reason}
        raise AssertionError(f"unexpected forced tool: {tool['name']}")

    client.call_forced_tool = fake
    validator = Validator(client=client)
    registry = JobRegistry()
    landlord = Landlord(
        config=config or OrchestratorConfig(),
        registry=registry,
        client=client,
        validator=validator,
        sdk_session_factory=_factory_for(sessions),
    )
    return LandlordServer(
        config=config or OrchestratorConfig(),
        landlord=landlord,
        default_output_dir=output_dir,
        registry=registry,
    )


async def _run_to_completion(server: LandlordServer, started: dict[str, Any]) -> dict[str, Any]:
    """Approve and wait until the job reaches a terminal state."""
    await server.approve_plan(job_id=started["job_id"])
    job = await server._registry.get(started["job_id"])
    assert job is not None
    while job.status == "running":
        await asyncio.sleep(0.01)
        job = await server._registry.get(started["job_id"])
    return await server.get_status(job_id=started["job_id"])


# =========================================================================== #
# Claim 1: Five-tool MCP surface (start, approve, status, artifacts, cancel).
#          Code actually exposes a sixth: run_orchestration.
# =========================================================================== #


def test_claim_documented_5_tools_exist_on_LandlordServer():
    """README: 'start_orchestration, approve_plan, get_status, get_artifacts, cancel.'"""
    for name in ("start_orchestration", "approve_plan", "get_status", "get_artifacts", "cancel"):
        assert hasattr(LandlordServer, name), f"missing claimed tool: {name}"


def test_documented_5_tool_count_understates_reality():
    """The MCP `main()` registers a 6th tool — `run_orchestration` — that the
    README does not list. This test pins the discrepancy so it shows up if the
    README is later updated."""
    import inspect

    from landlord import mcp_server

    src = inspect.getsource(mcp_server.main)
    decorators = src.count("@mcp.tool()")
    assert decorators == 6, (
        f"expected 6 @mcp.tool decorators (5 README + run_orchestration), got {decorators}"
    )


# =========================================================================== #
# Claim 2: start_orchestration returns plan awaiting approval + watch_command.
# =========================================================================== #


@pytest.mark.asyncio
async def test_start_orchestration_returns_awaiting_approval(tmp_path: Path):
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path)

    started = await server.start_orchestration(prompt="draft an essay")

    assert started["status"] == "awaiting_approval"
    assert "job_id" in started
    assert [c["role"] for c in started["plan"]] == ["writer"]
    assert "watch_command" in started, "README claims a watch_command is returned"
    assert started["job_id"] in started["watch_command"]
    assert started["output_dir"]


@pytest.mark.asyncio
async def test_start_orchestration_creates_job_directory(tmp_path: Path):
    """The returned `output_dir` is the *job-specific* directory (parent/<job_id>)."""
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path)

    started = await server.start_orchestration(prompt="p")

    job_dir = Path(started["output_dir"])
    assert job_dir.exists() and job_dir.is_dir()
    assert job_dir.name == started["job_id"]
    assert (job_dir / "shared").exists()
    assert (job_dir / "job.json").exists()


# =========================================================================== #
# Claim 3: Output-dir resolution honors absolute & relative paths.
# =========================================================================== #


@pytest.mark.asyncio
async def test_output_dir_absolute_path_preserved(tmp_path: Path):
    """An absolute output_dir argument is used as the parent directory verbatim."""
    explicit = tmp_path / "explicit"
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path / "default")

    started = await server.start_orchestration(prompt="p", output_dir=str(explicit))

    job_dir = Path(started["output_dir"])
    assert job_dir.parent.resolve() == explicit.resolve()
    assert (explicit / started["job_id"]).exists()


@pytest.mark.asyncio
async def test_output_dir_relative_resolved_against_cwd(tmp_path: Path, monkeypatch):
    """A relative output_dir is resolved against the current working directory."""
    monkeypatch.chdir(tmp_path)
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path / "default")

    started = await server.start_orchestration(prompt="p", output_dir="rel-out")

    expected = (tmp_path / "rel-out").resolve()
    assert Path(started["output_dir"]).parent.resolve() == expected


# =========================================================================== #
# Claim 4: approve_plan launches tenants and they reach terminal state.
# =========================================================================== #


@pytest.mark.asyncio
async def test_approve_plan_runs_tenants_to_completion(tmp_path: Path):
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path)

    started = await server.start_orchestration(prompt="p")
    status = await _run_to_completion(server, started)

    assert status["status"] == "complete"
    assert status["tenants"][0]["status"] == "complete"


@pytest.mark.asyncio
async def test_approve_plan_with_edits_replaces_plan_then_runs(tmp_path: Path):
    """Edits replace the plan AND tenants from the new plan are launched."""
    original = [_contract("writer")]
    new_plan = [_contract("editor")]

    sessions = {"editor": ScriptedSession("editor")}
    server = _build_server(original, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    edits = [c.model_dump() for c in new_plan]

    await server.approve_plan(job_id=started["job_id"], edits=edits)

    job = await server._registry.get(started["job_id"])
    while job.status == "running":
        await asyncio.sleep(0.01)
        job = await server._registry.get(started["job_id"])

    status = await server.get_status(job_id=started["job_id"])
    assert status["status"] == "complete"
    assert [t["role"] for t in status["tenants"]] == ["editor"]


@pytest.mark.asyncio
async def test_approve_plan_rejects_malformed_edits(tmp_path: Path):
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path)
    started = await server.start_orchestration(prompt="p")

    with pytest.raises(ValueError, match="Invalid edited plan"):
        await server.approve_plan(
            job_id=started["job_id"], edits=[{"not": "a contract"}]
        )


# =========================================================================== #
# Claim 5: get_artifacts is gated on terminal status; returns artifacts + files.
# =========================================================================== #


@pytest.mark.asyncio
async def test_get_artifacts_refuses_before_terminal(tmp_path: Path):
    plan = [_contract("writer")]
    server = _build_server(plan, {"writer": ScriptedSession("writer")}, tmp_path)
    started = await server.start_orchestration(prompt="p")

    with pytest.raises(ValueError, match="Artifacts not available"):
        await server.get_artifacts(job_id=started["job_id"])


@pytest.mark.asyncio
async def test_get_artifacts_returns_dict_keyed_by_role(tmp_path: Path):
    plan = [_contract("a"), _contract("b", depends_on=["a"])]
    sessions = {"a": ScriptedSession("a"), "b": ScriptedSession("b")}
    server = _build_server(plan, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    arts = await server.get_artifacts(job_id=started["job_id"])
    assert arts["status"] == "complete"
    assert arts["artifacts"] == {"a": {"x": "a-artifact"}, "b": {"x": "b-artifact"}}
    assert set(arts["files"].keys()) == {"a", "b"}


# =========================================================================== #
# Claim 6: cancel stops a running job, transitions to cancelled, emits event.
# =========================================================================== #


@pytest.mark.asyncio
async def test_cancel_emits_job_cancelled_event(tmp_path: Path):
    """Cancel writes a `job_cancelled` event to events.jsonl."""
    plan = [_contract("worker")]
    sessions = {"worker": ScriptedSession("worker", delay=10.0)}  # never finishes
    server = _build_server(plan, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    await server.approve_plan(job_id=started["job_id"])
    await asyncio.sleep(0.02)  # let tenant task spin up
    await server.cancel(job_id=started["job_id"])

    job = await server._registry.get(started["job_id"])
    events_path = job.output_dir / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert any(e["type"] == "job_cancelled" for e in events)


@pytest.mark.asyncio
async def test_cancel_unknown_job_raises(tmp_path: Path):
    server = _build_server([], {}, tmp_path)
    with pytest.raises(ValueError, match="Unknown job_id"):
        await server.cancel(job_id="nope")


# =========================================================================== #
# Claim 7: Two-tier validation — Tier 1 (JSON Schema) → Tier 2 (judge tool).
# =========================================================================== #


@pytest.mark.asyncio
async def test_judge_short_circuited_on_schema_failure(tmp_path: Path):
    """If Tier 1 (JSON Schema) fails, the LLM judge is NOT invoked at all."""
    judge_calls = {"n": 0}

    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        if tool["name"] == "judge_checkpoint":
            judge_calls["n"] += 1
            return {"passed": True, "reason": "ok"}
        raise AssertionError(tool["name"])

    client.call_forced_tool = fake
    validator = Validator(client=client)

    result = await validator.validate_checkpoint(
        output={"missing_required_field": True},
        checkpoint=_checkpoint(),
        contract=_contract("worker"),
    )
    assert result.passed is False
    assert result.tier == 1
    assert judge_calls["n"] == 0


@pytest.mark.asyncio
async def test_validation_runs_both_tiers_and_returns_tier2_result(tmp_path: Path):
    """Tier 1 passes (valid against schema), then judge_checkpoint runs."""
    judge_calls = {"n": 0}

    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        if tool["name"] == "judge_checkpoint":
            judge_calls["n"] += 1
            return {"passed": False, "reason": "off topic"}
        raise AssertionError(tool["name"])

    client.call_forced_tool = fake
    validator = Validator(client=client)

    result = await validator.validate_checkpoint(
        output={"x": "schema-valid"},
        checkpoint=_checkpoint(),
        contract=_contract("worker"),
    )
    assert result.passed is False
    assert result.tier == 2
    assert "off topic" in result.explanation
    assert judge_calls["n"] == 1


# =========================================================================== #
# Claim 8: Eviction & retry-with-fresh-context up to max_retries; then escalate.
# =========================================================================== #


@pytest.mark.asyncio
async def test_retry_context_propagates_last_error_to_next_attempt(tmp_path: Path):
    """README: 'evicted and retried with fresh context'.
    The next-attempt's system prompt must include the previous failure as retry_context."""
    plan = [_contract("worker", max_retries=2)]
    sessions = {"worker": ScriptedSession("worker")}
    captured_prompts: list[str] = []

    def factory(system_prompt, checkpoint_tools, work_dir, model, role=None, **kwargs):
        captured_prompts.append(system_prompt)
        return sessions["worker"]

    client = MagicMock(spec=AgentSDKClient)
    judge_count = {"n": 0}

    async def fake(system, messages, tool):
        if tool["name"] == "emit_plan":
            return {"contracts": [c.model_dump() for c in plan]}
        if tool["name"] == "judge_checkpoint":
            judge_count["n"] += 1
            return {"passed": False, "reason": f"attempt {judge_count['n']} bad"}
        raise AssertionError(tool["name"])

    client.call_forced_tool = fake
    validator = Validator(client=client)
    registry = JobRegistry()
    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=registry,
        client=client,
        validator=validator,
        sdk_session_factory=factory,
    )
    server = LandlordServer(
        config=OrchestratorConfig(),
        landlord=landlord,
        default_output_dir=tmp_path,
        registry=registry,
    )

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    assert len(captured_prompts) >= 2
    # Second attempt's system prompt must contain the first attempt's failure.
    assert "attempt 1 bad" in captured_prompts[1]
    assert "Retry context" in captured_prompts[1]


@pytest.mark.asyncio
async def test_tenant_escalates_after_max_retries_and_job_marked_partial(tmp_path: Path):
    plan = [_contract("worker", max_retries=2)]
    sessions = {"worker": ScriptedSession("worker")}
    server = _build_server(
        plan, sessions, tmp_path, judge_passes=False, judge_reason="bad"
    )

    started = await server.start_orchestration(prompt="p")
    status = await _run_to_completion(server, started)

    assert status["status"] == "partial"
    assert status["tenants"][0]["status"] == "escalated"
    assert status["tenants"][0]["retry_count"] == 2


# =========================================================================== #
# Claim 9: Default config from environment variables.
# =========================================================================== #


def test_orchestrator_config_from_env_picks_up_overrides(monkeypatch):
    monkeypatch.setenv("LANDLORD_LANDLORD_MODEL", "claude-test-landlord")
    monkeypatch.setenv("LANDLORD_TENANT_MODEL", "claude-test-tenant")
    monkeypatch.setenv("LANDLORD_MAX_RETRIES", "7")

    cfg = OrchestratorConfig.from_env()

    assert cfg.landlord_model == "claude-test-landlord"
    assert cfg.tenant_model == "claude-test-tenant"
    assert cfg.default_max_retries == 7


def test_orchestrator_config_from_env_defaults_match_readme(monkeypatch):
    """README configuration table values."""
    for k in ("LANDLORD_LANDLORD_MODEL", "LANDLORD_TENANT_MODEL", "LANDLORD_MAX_RETRIES"):
        monkeypatch.delenv(k, raising=False)

    cfg = OrchestratorConfig.from_env()

    assert cfg.landlord_model == "claude-opus-4-7"
    assert cfg.tenant_model == "claude-sonnet-4-6"
    assert cfg.default_max_retries == 3


@pytest.mark.asyncio
async def test_decompose_fills_default_max_retries_from_config(tmp_path: Path):
    """Contracts emitted by the model without explicit `max_retries` should
    inherit OrchestratorConfig.default_max_retries."""
    plan_no_retries = {
        "role": "x",
        "objective": "o",
        "sub_prompt": "p",
        "checkpoints": [{
            "name": "done",
            "description": "d",
            "schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        }],
        "output_schema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    }
    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        return {"contracts": [plan_no_retries]}

    client.call_forced_tool = fake

    landlord = Landlord(
        config=OrchestratorConfig(default_max_retries=9),
        registry=JobRegistry(),
        client=client,
        validator=MagicMock(spec=Validator),
        sdk_session_factory=lambda **kw: MagicMock(),
    )
    plan = await landlord.decompose("p")
    assert plan[0].max_retries == 9


# =========================================================================== #
# Claim 10: Dependency ordering — dependents wait for dependencies.
# =========================================================================== #


def test_resolve_launch_order_deps_before_dependents():
    plan = [
        _contract("c", depends_on=["b"]),
        _contract("b", depends_on=["a"]),
        _contract("a"),
    ]
    ordered = [c.role for c in resolve_launch_order(plan)]
    assert ordered.index("a") < ordered.index("b") < ordered.index("c")


@pytest.mark.asyncio
async def test_dependent_blocks_until_dependency_completes(tmp_path: Path):
    """The dependent's `started_at` must be later than the dependency's `finished_at`."""
    plan = [_contract("a"), _contract("b", depends_on=["a"])]
    a_session = ScriptedSession("a", delay=0.05)
    b_session = ScriptedSession("b")
    sessions = {"a": a_session, "b": b_session}
    server = _build_server(plan, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    assert a_session.finished_at is not None
    assert b_session.started_at is not None
    assert b_session.started_at >= a_session.finished_at


@pytest.mark.asyncio
async def test_dependent_system_prompt_includes_dependency_artifact(tmp_path: Path):
    """Dependents receive their dependency's emitted artifact in shared_context."""
    plan = [_contract("a"), _contract("b", depends_on=["a"])]
    a_session = ScriptedSession(
        "a", calls=[("emit_checkpoint__done", {"x": "alpha-result"})]
    )
    b_session = ScriptedSession("b")
    captured_prompts: dict[str, str] = {}

    def factory(system_prompt, checkpoint_tools, work_dir, model, role=None, **kwargs):
        captured_prompts[role] = system_prompt
        return {"a": a_session, "b": b_session}[role]

    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        if tool["name"] == "emit_plan":
            return {"contracts": [c.model_dump() for c in plan]}
        return {"passed": True, "reason": "ok"}

    client.call_forced_tool = fake
    validator = Validator(client=client)
    registry = JobRegistry()
    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=registry,
        client=client,
        validator=validator,
        sdk_session_factory=factory,
    )
    server = LandlordServer(
        config=OrchestratorConfig(),
        landlord=landlord,
        default_output_dir=tmp_path,
        registry=registry,
    )

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    assert "alpha-result" in captured_prompts["b"]
    assert "shared/a.json" in captured_prompts["b"]


@pytest.mark.asyncio
async def test_shared_artifact_file_written_after_dependency_passes(tmp_path: Path):
    """README: 'Every checkpoint output is validated... Artifact also available at shared/<role>.json'."""
    plan = [_contract("a")]
    sessions = {"a": ScriptedSession("a", calls=[("emit_checkpoint__done", {"x": "abc"})])}
    server = _build_server(plan, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    job = await server._registry.get(started["job_id"])
    shared = job.output_dir / "shared" / "a.json"
    assert shared.exists()
    assert json.loads(shared.read_text()) == {"x": "abc"}


# =========================================================================== #
# Claim 11: Event stream — full lifecycle events emitted to events.jsonl.
# =========================================================================== #


@pytest.mark.asyncio
async def test_happy_path_emits_full_event_lifecycle_in_order(tmp_path: Path):
    plan = [_contract("a"), _contract("b", depends_on=["a"])]
    sessions = {"a": ScriptedSession("a"), "b": ScriptedSession("b")}
    server = _build_server(plan, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    job = await server._registry.get(started["job_id"])
    events = [json.loads(line) for line in (job.output_dir / "events.jsonl").read_text().splitlines()]
    types = [e["type"] for e in events]

    assert types[0] == "job_created"
    assert "plan_approved" in types
    assert types.count("tenant_started") == 2
    assert types.count("checkpoint_passed") == 2
    assert types.count("tenant_complete") == 2
    assert types[-1] == "job_complete"

    # 'a' must complete before 'b' starts in event ordering.
    a_complete = next(i for i, t in enumerate(types) if t == "tenant_complete")
    b_started_after_a_complete = any(
        e["type"] == "tenant_started" and e["role"] == "b"
        and types.index("tenant_started", types.index("tenant_complete")) >= a_complete
        for e in events
    )
    assert b_started_after_a_complete


@pytest.mark.asyncio
async def test_eviction_emits_failed_evicted_retrying_events(tmp_path: Path):
    plan = [_contract("worker", max_retries=2)]
    sessions = {"worker": ScriptedSession("worker")}
    server = _build_server(plan, sessions, tmp_path, judge_passes=False, judge_reason="x")

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    job = await server._registry.get(started["job_id"])
    events = [json.loads(line) for line in (job.output_dir / "events.jsonl").read_text().splitlines()]
    types = [e["type"] for e in events]

    assert types.count("checkpoint_failed") >= 1
    assert types.count("tenant_evicted") >= 1
    assert types.count("tenant_retrying") >= 1
    assert "tenant_escalated" in types
    assert "job_partial" in types


# =========================================================================== #
# Claim 12: Job sidecar (job.json) reflects live status.
# =========================================================================== #


@pytest.mark.asyncio
async def test_job_sidecar_reflects_current_status(tmp_path: Path):
    plan = [_contract("w")]
    sessions = {"w": ScriptedSession("w")}
    server = _build_server(plan, sessions, tmp_path)

    started = await server.start_orchestration(prompt="p")
    await _run_to_completion(server, started)

    job = await server._registry.get(started["job_id"])
    sidecar = json.loads((job.output_dir / "job.json").read_text())
    assert sidecar["status"] == "complete"
    assert sidecar["tenants"][0]["status"] == "complete"
    assert sidecar["approved_at"] is not None


# =========================================================================== #
# Claim 13: Permission auto-approval list (Read/Grep/Glob/checkpoints, etc.).
# =========================================================================== #


def test_auto_approve_set_matches_documented_tools():
    """Hard-coded set in mcp_server matches the documented intent."""
    assert {
        "Read", "Grep", "Glob", "LS",
        "WebFetch", "WebSearch",
        "TodoRead", "TodoWrite",
    } == _AUTO_APPROVE_TOOLS


def test_auto_approve_rules_for_known_tools():
    for t in _AUTO_APPROVE_TOOLS:
        assert _is_auto_approved(t), f"{t} should be auto-approved"
    assert _is_auto_approved("mcp__checkpoints__emit_checkpoint__done")
    # Anything writing or mutating must NOT be auto-approved.
    for t in ("Write", "Edit", "Bash", "NotebookEdit"):
        assert not _is_auto_approved(t), f"{t} should NOT be auto-approved"


def test_auto_approve_prefixes_includes_checkpoints():
    assert "mcp__checkpoints__" in _AUTO_APPROVE_PREFIXES


# =========================================================================== #
# Claim 14: SDK adapter forwards the documented session options.
# README: setting_sources=["user"], skills="all", add_dirs=[cwd], sandboxed cwd.
# =========================================================================== #


@pytest.mark.asyncio
async def test_sdk_adapter_passes_documented_options(tmp_path: Path):
    """Verify the SDK adapter constructs ClaudeAgentOptions with the documented values.

    Covers README claims 'Tenants inherit your Claude Code config — Skills,
    CLAUDE.md, hooks, user MCP servers — all available inside every tenant via
    setting_sources=["user"] and skills="all"' and 'Read access to the directory
    the MCP server was launched from'.
    """
    captured_options: dict = {}

    class FakeOptions:
        def __init__(self, **kwargs):
            captured_options.update(kwargs)

    class FakeClient:
        def __init__(self, options=None):
            self._options = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def query(self, prompt):
            return None

        async def receive_response(self):
            if False:
                yield None  # async generator
            return

    def fake_create_mcp(name, version, tools):
        return MagicMock(name=name)

    def fake_tool(name, desc, schema):
        def deco(fn):
            return fn
        return deco

    adapter = _SDKSessionAdapter(
        system_prompt="You are a worker.",
        checkpoint_tools=[
            {"name": "emit_checkpoint__done", "description": "x", "input_schema": {"type": "object"}}
        ],
        work_dir=tmp_path,
        model="claude-sonnet-4-6",
        ClaudeAgentOptions=FakeOptions,
        ClaudeSDKClient=FakeClient,
        create_sdk_mcp_server=fake_create_mcp,
        tool=fake_tool,
        role="worker",
    )

    async def noop(name, args):
        return {"ok": True}

    await adapter.run(sub_prompt="go", on_checkpoint=noop)

    assert captured_options["setting_sources"] == ["user"]
    assert captured_options["skills"] == "all"
    assert captured_options["cwd"] == str(tmp_path)
    assert "add_dirs" in captured_options
    assert captured_options["model"] == "claude-sonnet-4-6"
    # Without a permission_callback, autonomous mode → bypassPermissions.
    assert captured_options.get("permission_mode") == "bypassPermissions"


@pytest.mark.asyncio
async def test_sdk_adapter_writes_session_log_in_tenant_dir(tmp_path: Path):
    class FakeOptions:
        def __init__(self, **kwargs):
            pass

    class FakeClient:
        def __init__(self, options=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def query(self, prompt):
            return None

        async def receive_response(self):
            if False:
                yield None
            return

    adapter = _SDKSessionAdapter(
        system_prompt="x", checkpoint_tools=[], work_dir=tmp_path, model="m",
        ClaudeAgentOptions=FakeOptions, ClaudeSDKClient=FakeClient,
        create_sdk_mcp_server=lambda **k: MagicMock(),
        tool=lambda *a, **k: (lambda f: f),
        role="worker",
    )

    async def noop(*a):
        return {"ok": True}

    await adapter.run(sub_prompt="go", on_checkpoint=noop)
    log_path = tmp_path / "session.log"
    assert log_path.exists()
    assert "tenant session start" in log_path.read_text()


# =========================================================================== #
# Claim 15: Forced-tool failure raises RuntimeError (not silently passes).
# =========================================================================== #


@pytest.mark.asyncio
async def test_call_forced_tool_raises_when_model_does_not_call_tool():
    """README: 'no I hope the model said PASS' — a non-call must hard-raise."""

    async def empty_query(prompt, options):
        if False:
            yield  # async generator that yields nothing

    client = AgentSDKClient(model="m", query_fn=empty_query)
    with pytest.raises(RuntimeError, match="did not call forced tool"):
        await client.call_forced_tool(
            system="s",
            messages=[{"role": "user", "content": "u"}],
            tool={"name": "judge_checkpoint", "description": "d",
                  "input_schema": {"type": "object", "properties": {}, "required": []}},
        )


# =========================================================================== #
# Claim 16: Format helper for progress notifications.
# =========================================================================== #


def test_format_event_message_covers_each_event_type():
    msgs = {
        "job_created": {"type": "job_created", "plan": [{}, {}]},
        "plan_approved": {"type": "plan_approved"},
        "tenant_started": {"type": "tenant_started", "role": "x"},
        "checkpoint_passed": {"type": "checkpoint_passed", "role": "x", "checkpoint": "done"},
        "checkpoint_failed": {"type": "checkpoint_failed", "role": "x", "checkpoint": "done", "reason": "nope"},
        "tenant_retrying": {"type": "tenant_retrying", "role": "x", "retry": 1},
        "tenant_evicted": {"type": "tenant_evicted", "role": "x", "reason": "bad"},
        "tenant_escalated": {"type": "tenant_escalated", "role": "x", "retry": 3},
        "tenant_complete": {"type": "tenant_complete", "role": "x"},
        "job_complete": {"type": "job_complete"},
        "job_partial": {"type": "job_partial"},
        "job_cancelled": {"type": "job_cancelled"},
    }
    for label, ev in msgs.items():
        out = _format_event_message(ev)
        assert out, f"no message for {label}"
        assert isinstance(out, str)


# =========================================================================== #
# Claim 17: Build default server uses LANDLORD_OUTPUT_DIR.
# =========================================================================== #


def test_build_default_server_honors_output_dir_env(monkeypatch, tmp_path: Path):
    target = tmp_path / "envdir"
    monkeypatch.setenv("LANDLORD_OUTPUT_DIR", str(target))
    # build_default_server constructs a real AgentSDKClient via claude_agent_sdk —
    # importing succeeded in the baseline run, so this should work end-to-end.
    server = build_default_server()
    assert server._default_output_dir.resolve() == target.resolve()
    assert target.exists()


# =========================================================================== #
# Claim 18: Plan with cycle is rejected at decompose() and at edit time.
# =========================================================================== #


@pytest.mark.asyncio
async def test_decompose_rejects_cyclic_plan_from_model():
    cyclic = [
        {"role": "a", "objective": "o", "sub_prompt": "p",
         "checkpoints": [{"name": "n", "description": "d", "schema": {"type": "object"}}],
         "output_schema": {"type": "object"}, "depends_on": ["b"]},
        {"role": "b", "objective": "o", "sub_prompt": "p",
         "checkpoints": [{"name": "n", "description": "d", "schema": {"type": "object"}}],
         "output_schema": {"type": "object"}, "depends_on": ["a"]},
    ]
    client = MagicMock(spec=AgentSDKClient)

    async def fake(system, messages, tool):
        return {"contracts": cyclic}

    client.call_forced_tool = fake
    landlord = Landlord(
        config=OrchestratorConfig(),
        registry=JobRegistry(),
        client=client,
        validator=MagicMock(spec=Validator),
        sdk_session_factory=lambda **kw: MagicMock(),
    )
    from landlord.orchestrator import DependencyCycleError
    with pytest.raises(DependencyCycleError):
        await landlord.decompose("p")
