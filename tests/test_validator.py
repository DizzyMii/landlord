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
