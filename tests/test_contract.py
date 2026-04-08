import pytest
from landlord.contract import Checkpoint, Contract


class TestCheckpoint:
    def test_create_checkpoint(self):
        cp = Checkpoint(
            name="schema_defined",
            description="Database schema is defined",
            schema={"type": "object", "properties": {"tables": {"type": "array"}}},
        )
        assert cp.name == "schema_defined"
        assert cp.description == "Database schema is defined"
        assert cp.schema["type"] == "object"

    def test_checkpoint_requires_all_fields(self):
        with pytest.raises(Exception):
            Checkpoint(name="test")


class TestContract:
    def test_create_contract_with_defaults(self):
        contract = Contract(
            role="backend_engineer",
            objective="Build a REST API",
            sub_prompt="You are a backend engineer. Build a REST API with user auth.",
            checkpoints=[
                Checkpoint(
                    name="api_routes",
                    description="API routes are defined",
                    schema={"type": "object"},
                )
            ],
            output_schema={"type": "object"},
        )
        assert contract.role == "backend_engineer"
        assert contract.max_retries == 3
        assert contract.depends_on == []
        assert contract.context is None
        assert contract.tools_allowed is None
        assert contract.tools_denied is None
        assert contract.tenant_id  # auto-generated, non-empty

    def test_tenant_id_auto_generated_unique(self):
        c1 = Contract(
            role="a", objective="x", sub_prompt="x",
            checkpoints=[], output_schema={},
        )
        c2 = Contract(
            role="a", objective="x", sub_prompt="x",
            checkpoints=[], output_schema={},
        )
        assert c1.tenant_id != c2.tenant_id

    def test_contract_serialization_roundtrip(self):
        contract = Contract(
            role="analyst",
            objective="Analyze data",
            sub_prompt="Analyze the dataset",
            checkpoints=[
                Checkpoint(name="loaded", description="Data loaded", schema={"type": "object"})
            ],
            output_schema={"type": "object"},
            depends_on=["data_engineer"],
        )
        data = contract.model_dump()
        restored = Contract(**data)
        assert restored.role == contract.role
        assert restored.depends_on == ["data_engineer"]
        assert len(restored.checkpoints) == 1

    def test_effective_tools_whitelist(self):
        contract = Contract(
            role="writer", objective="x", sub_prompt="x",
            checkpoints=[], output_schema={},
            tools_allowed=["file_write", "file_read"],
        )
        result = contract.effective_tools(["file_write", "file_read", "shell_exec", "web_search"])
        assert sorted(result) == ["file_read", "file_write"]

    def test_effective_tools_blacklist(self):
        contract = Contract(
            role="writer", objective="x", sub_prompt="x",
            checkpoints=[], output_schema={},
            tools_denied=["shell_exec"],
        )
        all_tools = ["file_write", "file_read", "shell_exec", "web_search"]
        result = contract.effective_tools(all_tools)
        assert "shell_exec" not in result
        assert sorted(result) == ["file_read", "file_write", "web_search"]

    def test_effective_tools_whitelist_takes_precedence(self):
        contract = Contract(
            role="writer", objective="x", sub_prompt="x",
            checkpoints=[], output_schema={},
            tools_allowed=["file_write"],
            tools_denied=["file_write"],  # should be ignored
        )
        result = contract.effective_tools(["file_write", "file_read", "shell_exec"])
        assert result == ["file_write"]

    def test_effective_tools_no_restrictions(self):
        contract = Contract(
            role="writer", objective="x", sub_prompt="x",
            checkpoints=[], output_schema={},
        )
        all_tools = ["file_write", "file_read", "shell_exec"]
        result = contract.effective_tools(all_tools)
        assert result == all_tools
