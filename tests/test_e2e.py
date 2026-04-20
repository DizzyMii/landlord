"""End-to-end smoke test with mocked Anthropic + SDK."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.agent_sdk_client import AgentSDKClient
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
    mock_client = MagicMock(spec=AgentSDKClient)
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

    assert call_log.count("emit_plan") == 1
    assert call_log.count("judge_checkpoint") >= 2

    shared_backend = job.output_dir / "shared" / "backend.json"
    assert shared_backend.exists()
