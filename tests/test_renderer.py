import pytest
from io import StringIO
from rich.console import Console
from landlord.renderer import Renderer
from landlord.contract import Contract, Checkpoint


def make_contract(role="worker", tenant_id="abc"):
    return Contract(
        tenant_id=tenant_id,
        role=role,
        objective="Test",
        sub_prompt="Do test",
        checkpoints=[Checkpoint(name="cp1", description="Check", schema={"type": "object"})],
        output_schema={"type": "object"},
    )


class TestRenderer:
    @pytest.fixture
    def renderer(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        return Renderer(console=console), buf

    def test_show_plan(self, renderer):
        r, buf = renderer
        contracts = [make_contract("backend"), make_contract("frontend")]
        r.show_plan(contracts)
        output = buf.getvalue()
        assert "backend" in output
        assert "frontend" in output

    def test_tenant_started(self, renderer):
        r, buf = renderer
        r.tenant_started(make_contract("worker", "t1"))
        output = buf.getvalue()
        assert "worker" in output.lower() or "t1" in output

    def test_checkpoint_passed(self, renderer):
        r, buf = renderer
        r.checkpoint_passed("t1", "schema_done")
        output = buf.getvalue()
        assert "schema_done" in output

    def test_checkpoint_failed(self, renderer):
        r, buf = renderer
        r.checkpoint_failed("t1", "schema_done", "Missing tables field")
        output = buf.getvalue()
        assert "schema_done" in output
        assert "Missing tables" in output

    def test_tenant_evicted(self, renderer):
        r, buf = renderer
        r.tenant_evicted("t1", "Validation failed")
        output = buf.getvalue()
        assert "evict" in output.lower() or "t1" in output

    def test_tenant_completed(self, renderer):
        r, buf = renderer
        r.tenant_completed("t1")
        output = buf.getvalue()
        assert "t1" in output or "complete" in output.lower()
