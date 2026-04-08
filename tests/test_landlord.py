import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from landlord.landlord import Landlord
from landlord.config import LandlordConfig
from landlord.contract import Contract, Checkpoint
from landlord.event_bus import EventBus, Event
from landlord.llm_client import LLMClient
from landlord.validator import Validator, ValidationResult
from landlord.renderer import Renderer


def sample_contracts_json():
    return json.dumps([
        {
            "role": "backend_engineer",
            "objective": "Build REST API",
            "sub_prompt": "Build a REST API with user authentication",
            "checkpoints": [
                {"name": "routes_defined", "description": "API routes exist", "schema": {"type": "object"}}
            ],
            "output_schema": {"type": "object"},
            "depends_on": [],
        },
        {
            "role": "frontend_engineer",
            "objective": "Build React dashboard",
            "sub_prompt": "Build a React dashboard that consumes the API",
            "checkpoints": [
                {"name": "components_done", "description": "Components built", "schema": {"type": "object"}}
            ],
            "output_schema": {"type": "object"},
            "depends_on": ["backend_engineer"],
        },
    ])


@pytest.fixture
def config():
    return LandlordConfig(auto_approve=True, output_dir="./test_output")


@pytest.fixture
def mock_llm():
    client = MagicMock(spec=LLMClient)
    client.model = "test-model"
    return client


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_validator():
    v = MagicMock(spec=Validator)
    v.validate_checkpoint = AsyncMock(
        return_value=ValidationResult(passed=True, tier=1, explanation="OK")
    )
    return v


@pytest.fixture
def mock_renderer():
    return MagicMock(spec=Renderer)


class TestDecompose:
    async def test_decompose_returns_contracts(self, config, mock_llm, bus, mock_validator, mock_renderer):
        mock_llm.chat = AsyncMock(return_value=sample_contracts_json())

        landlord = Landlord(
            config=config, llm_client=mock_llm, event_bus=bus,
            validator=mock_validator, renderer=mock_renderer,
        )
        contracts = await landlord.decompose("Build a REST API with auth and a React dashboard")
        assert len(contracts) == 2
        assert contracts[0].role == "backend_engineer"
        assert contracts[1].depends_on == ["backend_engineer"]

    async def test_decompose_retries_on_bad_json(self, config, mock_llm, bus, mock_validator, mock_renderer):
        mock_llm.chat = AsyncMock(side_effect=[
            "not valid json {{{",
            sample_contracts_json(),
        ])

        landlord = Landlord(
            config=config, llm_client=mock_llm, event_bus=bus,
            validator=mock_validator, renderer=mock_renderer,
        )
        contracts = await landlord.decompose("Build something")
        assert len(contracts) == 2


class TestEviction:
    async def test_eviction_on_validation_failure(self, config, mock_llm, bus, mock_validator, mock_renderer, tmp_path):
        config.output_dir = str(tmp_path / "output")
        mock_validator.validate_checkpoint = AsyncMock(
            return_value=ValidationResult(passed=False, tier=1, explanation="Bad schema", errors=["missing field"])
        )

        landlord = Landlord(
            config=config, llm_client=mock_llm, event_bus=bus,
            validator=mock_validator, renderer=mock_renderer,
        )

        contract = Contract(
            tenant_id="t1", role="worker", objective="Test",
            sub_prompt="Do work", checkpoints=[
                Checkpoint(name="cp1", description="Check", schema={"type": "object"})
            ],
            output_schema={"type": "object"}, max_retries=1,
        )

        future = asyncio.get_event_loop().create_future()
        event = Event(
            tenant_id="t1", event_type="checkpoint_reached",
            payload={"name": "cp1", "output": {"bad": "data"}, "future": future},
        )

        landlord._active_contracts = {"t1": contract}
        landlord._retry_counts = {"t1": 0}
        landlord._active_tasks = {"t1": MagicMock()}

        await landlord.handle_checkpoint(event)

        result = future.result()
        assert result.passed is False
        mock_renderer.checkpoint_failed.assert_called_once()


class TestDependencyOrdering:
    async def test_dependent_tenant_waits(self, config, mock_llm, bus, mock_validator, mock_renderer, tmp_path):
        config.output_dir = str(tmp_path / "output")

        contract_a = Contract(
            tenant_id="a1", role="data_engineer", objective="Produce data",
            sub_prompt="Produce data", checkpoints=[], output_schema={"type": "object"},
        )
        contract_b = Contract(
            tenant_id="b1", role="analyst", objective="Analyze data",
            sub_prompt="Analyze data", checkpoints=[], output_schema={"type": "object"},
            depends_on=["data_engineer"],
        )

        landlord = Landlord(
            config=config, llm_client=mock_llm, event_bus=bus,
            validator=mock_validator, renderer=mock_renderer,
        )

        order = landlord._resolve_launch_order([contract_a, contract_b])
        roles_in_order = [c.role for c in order]
        assert roles_in_order.index("data_engineer") < roles_in_order.index("analyst")
