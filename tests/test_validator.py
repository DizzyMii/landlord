import pytest
from unittest.mock import AsyncMock, MagicMock
from landlord.validator import Validator
from landlord.contract import Checkpoint, Contract
from landlord.llm_client import LLMClient


@pytest.fixture
def checkpoint():
    return Checkpoint(
        name="schema_ready",
        description="Database schema is defined with at least one table",
        schema={
            "type": "object",
            "properties": {"tables": {"type": "array", "items": {"type": "string"}}},
            "required": ["tables"],
        },
    )


@pytest.fixture
def contract(checkpoint):
    return Contract(
        role="db_engineer",
        objective="Design database schema",
        sub_prompt="Design a database schema",
        checkpoints=[checkpoint],
        output_schema={"type": "object"},
    )


@pytest.fixture
def mock_llm_client():
    return MagicMock(spec=LLMClient)


class TestValidator:
    async def test_tier1_pass(self, mock_llm_client, checkpoint, contract):
        validator = Validator(llm_client=mock_llm_client)
        result = await validator.validate_checkpoint(
            output={"tables": ["users", "posts"]},
            checkpoint=checkpoint,
            contract=contract,
        )
        assert result.passed is True
        assert result.tier == 1

    async def test_tier1_fail_missing_field(self, mock_llm_client, checkpoint, contract):
        validator = Validator(llm_client=mock_llm_client)
        result = await validator.validate_checkpoint(
            output={"columns": ["id"]},
            checkpoint=checkpoint,
            contract=contract,
        )
        assert result.passed is False
        assert result.tier == 1
        assert len(result.errors) > 0

    async def test_tier1_fail_wrong_type(self, mock_llm_client, checkpoint, contract):
        validator = Validator(llm_client=mock_llm_client)
        result = await validator.validate_checkpoint(
            output={"tables": "not_an_array"},
            checkpoint=checkpoint,
            contract=contract,
        )
        assert result.passed is False
        assert result.tier == 1

    async def test_tier3_semantic_check(self, mock_llm_client, checkpoint, contract):
        mock_llm_client.chat = AsyncMock(return_value="PASS: The output contains valid table definitions.")
        validator = Validator(llm_client=mock_llm_client)
        result = await validator.validate_checkpoint(
            output={"tables": ["users"]},
            checkpoint=checkpoint,
            contract=contract,
        )
        assert result.passed is True
        assert result.tier == 3

    async def test_tier3_semantic_fail(self, mock_llm_client, checkpoint, contract):
        mock_llm_client.chat = AsyncMock(return_value="FAIL: No tables were actually defined, just empty names.")
        validator = Validator(llm_client=mock_llm_client)
        result = await validator.validate_checkpoint(
            output={"tables": ["users"]},
            checkpoint=checkpoint,
            contract=contract,
        )
        assert result.passed is False
        assert result.tier == 3
