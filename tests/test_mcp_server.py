"""Tests for the MCP server tool handlers.

These tests exercise the in-process tool handlers without actually starting the MCP
stdio server. The handlers are pure functions over the LandlordServer instance.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.contract import Checkpoint, Contract
from landlord.jobs import JobRegistry
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
    registry = JobRegistry()
    s = LandlordServer(
        config=OrchestratorConfig(),
        landlord=mock_landlord,
        default_output_dir=tmp_path,
        registry=registry,
    )
    s._mock_landlord = mock_landlord
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
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    server._mock_landlord.launch = AsyncMock()
    server._mock_landlord.wait_until_done = AsyncMock()
    started = await server.start_orchestration(prompt="p")

    job = await server._registry.get(started["job_id"])
    assert job is not None

    async def hang():
        await asyncio.sleep(10)

    fake_task = asyncio.create_task(hang())
    next(iter(job.tenants.values())).task = fake_task

    await server._registry.transition(started["job_id"], "running")
    result = await server.cancel(job_id=started["job_id"])
    assert result["status"] == "cancelled"
    await asyncio.sleep(0.01)
    assert fake_task.cancelled()


@pytest.mark.asyncio
async def test_cancel_rejects_terminal_status(server):
    server._mock_landlord.decompose = AsyncMock(return_value=[_c("worker")])
    started = await server.start_orchestration(prompt="p")
    await server._registry.transition(started["job_id"], "complete")
    with pytest.raises(ValueError, match="Cannot cancel"):
        await server.cancel(job_id=started["job_id"])
