import pytest
from landlord.dashboard import Dashboard, MODEL_PRICING


class TestDashboard:
    @pytest.fixture
    def dashboard(self):
        return Dashboard(model="gpt-4o")

    def test_initial_state(self, dashboard):
        assert dashboard.total_tokens == 0
        assert dashboard.estimated_cost == 0.0
        assert dashboard.tenant_statuses == {}

    def test_update_tokens(self, dashboard):
        dashboard.update_tokens(prompt_tokens=100, completion_tokens=50)
        assert dashboard.total_tokens == 150
        assert dashboard.estimated_cost > 0

    def test_cost_calculation_gpt4o(self, dashboard):
        dashboard.update_tokens(prompt_tokens=1000, completion_tokens=500)
        expected = 1000 * MODEL_PRICING["gpt-4o"]["input"] + 500 * MODEL_PRICING["gpt-4o"]["output"]
        assert abs(dashboard.estimated_cost - expected) < 0.0001

    def test_cost_unknown_model(self):
        d = Dashboard(model="unknown-model-xyz")
        d.update_tokens(prompt_tokens=100, completion_tokens=50)
        assert d.total_tokens == 150
        assert d.estimated_cost == 0.0

    def test_tenant_status_update(self, dashboard):
        dashboard.set_tenant_status("t1", "backend_engineer", "running")
        assert dashboard.tenant_statuses["t1"] == ("backend_engineer", "running")

    def test_tenant_status_overwrite(self, dashboard):
        dashboard.set_tenant_status("t1", "backend", "running")
        dashboard.set_tenant_status("t1", "backend", "complete")
        assert dashboard.tenant_statuses["t1"] == ("backend", "complete")

    def test_render_returns_renderable(self, dashboard):
        dashboard.set_tenant_status("t1", "backend", "running")
        dashboard.update_tokens(prompt_tokens=2400, completion_tokens=100)
        result = dashboard.render()
        assert result is not None
