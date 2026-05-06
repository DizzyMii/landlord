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
async def test_registry_transition_raises_unknown_job_error_for_unknown_id():
    from landlord.jobs import UnknownJobError
    reg = JobRegistry()
    with pytest.raises(UnknownJobError):
        await reg.transition("nonexistent", "running")


@pytest.mark.asyncio
async def test_registry_replace_plan_raises_unknown_job_error_for_unknown_id():
    from landlord.jobs import UnknownJobError
    reg = JobRegistry()
    with pytest.raises(UnknownJobError):
        await reg.replace_plan("nonexistent", [_simple_contract("x")])


def test_emit_event_appends_jsonl(tmp_path: Path):
    plan = [_simple_contract("a")]
    job = Job.create(prompt="p", plan=plan, output_dir=tmp_path)

    job.emit_event("job_created", prompt="p")
    job.emit_event("tenant_started", tenant_id=plan[0].tenant_id, role="a")
    job.emit_event("tenant_complete", tenant_id=plan[0].tenant_id, role="a")

    events_path = job.output_dir / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text().strip().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [e["type"] for e in parsed] == ["job_created", "tenant_started", "tenant_complete"]
    assert all(e["job_id"] == job.job_id for e in parsed)
    assert all("ts" in e for e in parsed)
    assert parsed[0]["prompt"] == "p"
    assert parsed[1]["role"] == "a"


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
