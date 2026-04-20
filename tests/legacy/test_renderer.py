import pytest
from io import StringIO
from rich.console import Console
from landlord.legacy.renderer import TenantPanel, LiveRenderer
from landlord.contract import Contract, Checkpoint
from landlord.legacy.dashboard import Dashboard


def make_contract(role="worker", tenant_id="abc"):
    return Contract(
        tenant_id=tenant_id,
        role=role,
        objective="Test",
        sub_prompt="Do test",
        checkpoints=[Checkpoint(name="cp1", description="Check", schema={"type": "object"})],
        output_schema={"type": "object"},
    )


class TestTenantPanel:
    def test_create_panel(self):
        contract = make_contract("backend", "t1")
        panel = TenantPanel(contract)
        assert panel.status == "pending"
        assert len(panel.lines) == 0

    def test_add_line(self):
        panel = TenantPanel(make_contract())
        panel.add_line("Writing API routes...")
        assert len(panel.lines) == 1
        assert "Writing API routes" in panel.lines[0]

    def test_lines_capped_at_max(self):
        panel = TenantPanel(make_contract(), max_lines=3)
        for i in range(10):
            panel.add_line(f"Line {i}")
        assert len(panel.lines) == 3
        assert "Line 9" in panel.lines[-1]

    def test_render_returns_panel(self):
        panel = TenantPanel(make_contract("backend", "t1"))
        panel.status = "running"
        panel.add_line("Working...")
        result = panel.render()
        assert result is not None

    def test_status_colors(self):
        panel = TenantPanel(make_contract())
        panel.status = "running"
        rendered = panel.render()
        assert rendered.border_style == "blue"

        panel.status = "complete"
        rendered = panel.render()
        assert rendered.border_style == "green"


class TestLiveRenderer:
    @pytest.fixture
    def renderer(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        dashboard = Dashboard(model="gpt-4o")
        return LiveRenderer(console=console, dashboard=dashboard), buf

    def test_show_plan(self, renderer):
        r, buf = renderer
        contracts = [make_contract("backend"), make_contract("frontend")]
        r.show_plan(contracts)
        output = buf.getvalue()
        assert "backend" in output
        assert "frontend" in output

    def test_tenant_started_creates_panel(self, renderer):
        r, buf = renderer
        contract = make_contract("backend", "t1")
        r.tenant_started(contract)
        assert "t1" in r._panels
        assert r._panels["t1"].status == "running"

    def test_checkpoint_passed(self, renderer):
        r, buf = renderer
        contract = make_contract("backend", "t1")
        r.tenant_started(contract)
        r.checkpoint_passed("t1", "routes_defined")
        assert any("routes_defined" in line and "passed" in line for line in r._panels["t1"].lines)

    def test_checkpoint_failed(self, renderer):
        r, buf = renderer
        contract = make_contract("backend", "t1")
        r.tenant_started(contract)
        r.checkpoint_failed("t1", "routes_defined", "Missing field")
        assert any("routes_defined" in line and "failed" in line for line in r._panels["t1"].lines)

    def test_tenant_evicted(self, renderer):
        r, buf = renderer
        contract = make_contract("backend", "t1")
        r.tenant_started(contract)
        r.tenant_evicted("t1", "Bad output")
        assert r._panels["t1"].status == "failed"

    def test_tenant_completed(self, renderer):
        r, buf = renderer
        contract = make_contract("backend", "t1")
        r.tenant_started(contract)
        r.tenant_completed("t1")
        assert r._panels["t1"].status == "complete"

    def test_prompt_approval_yes(self, renderer, monkeypatch):
        r, buf = renderer
        monkeypatch.setattr(r._console, "input", lambda prompt="": "y")
        assert r.prompt_approval() is True

    def test_show_error(self, renderer):
        r, buf = renderer
        r.show_error("Something broke")
        output = buf.getvalue()
        assert "Something broke" in output
