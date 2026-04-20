# Interactive CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Landlord CLI into an interactive REPL with real-time stacked tenant panels, a persistent status dashboard, cost tracking, and interrupt support.

**Architecture:** The Renderer is rewritten as a `LiveRenderer` using `rich.live.Live` with stacked `Panel`s per tenant. A new `Dashboard` class tracks token usage and cost. A new `Repl` class wraps the session loop. The `cli.py` detects interactive vs one-shot mode. The Landlord and its backend logic are untouched — only the display layer changes.

**Tech Stack:** Python 3.11+, rich (Live, Panel, Table, Console), existing landlord internals

**Spec:** `docs/superpowers/specs/2026-04-08-interactive-cli-design.md`

---

## File Structure

```
landlord/
├── __init__.py          # Modified: add __version__
├── cli.py               # Modified: detect interactive vs one-shot, wire up new renderer
├── repl.py              # New: REPL loop, welcome screen, slash commands
├── dashboard.py         # New: status bar, cost tracking, token aggregation
├── renderer.py          # Rewritten: LiveRenderer with TenantPanel (keeps same public interface)
├── llm_client.py        # Unchanged (already has token tracking)
├── landlord.py          # Unchanged
└── ...
tests/
├── test_dashboard.py    # New
├── test_repl.py         # New
├── test_renderer.py     # Rewritten to match new LiveRenderer
├── test_cli.py          # Modified for interactive mode detection
└── ...
```

---

## Task 1: Dashboard — Cost & Token Tracking

**Files:**
- Create: `landlord/dashboard.py`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from landlord.dashboard import Dashboard, MODEL_PRICING
from landlord.llm_client import TokenUsage


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
        assert d.estimated_cost == 0.0  # unknown model, no pricing

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
        # Should return a Rich renderable (has __rich_console__ or is a str)
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement Dashboard**

```python
"""Status dashboard with token usage and cost tracking."""

from __future__ import annotations

from rich.text import Text


MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "claude-sonnet": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "claude-haiku": {"input": 0.25 / 1_000_000, "output": 1.25 / 1_000_000},
    "claude-opus": {"input": 15.00 / 1_000_000, "output": 75.00 / 1_000_000},
}

STATUS_INDICATORS = {
    "running": ("[green]●[/green]", "green"),
    "waiting": ("[yellow]●[/yellow]", "yellow"),
    "pending": ("[dim]○[/dim]", "dim"),
    "complete": ("[green]✓[/green]", "green"),
    "failed": ("[red]✗[/red]", "red"),
    "escalated": ("[bold yellow]⚠[/bold yellow]", "bold yellow"),
}


def _match_model_pricing(model: str) -> dict[str, float] | None:
    """Match a model name to pricing by longest prefix."""
    best_match = None
    best_len = 0
    for prefix, pricing in MODEL_PRICING.items():
        if model.startswith(prefix) and len(prefix) > best_len:
            best_match = pricing
            best_len = len(prefix)
    return best_match


class Dashboard:
    """Persistent status bar with token usage and cost tracking."""

    def __init__(self, model: str) -> None:
        self._model = model
        self._pricing = _match_model_pricing(model)
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._tenant_statuses: dict[str, tuple[str, str]] = {}  # id -> (role, status)

    @property
    def total_tokens(self) -> int:
        return self._prompt_tokens + self._completion_tokens

    @property
    def estimated_cost(self) -> float:
        if not self._pricing:
            return 0.0
        return (
            self._prompt_tokens * self._pricing["input"]
            + self._completion_tokens * self._pricing["output"]
        )

    @property
    def tenant_statuses(self) -> dict[str, tuple[str, str]]:
        return dict(self._tenant_statuses)

    def update_tokens(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens

    def set_tenant_status(self, tenant_id: str, role: str, status: str) -> None:
        self._tenant_statuses[tenant_id] = (role, status)

    def render(self) -> Text:
        """Render the status bar as a Rich Text object."""
        parts = []

        # Tenant indicators
        if self._tenant_statuses:
            tenant_parts = []
            for _tid, (role, status) in self._tenant_statuses.items():
                indicator = STATUS_INDICATORS.get(status, ("[dim]?[/dim]", "dim"))[0]
                tenant_parts.append(f"{indicator} {role}({status})")
            parts.append("Tenants: " + "  ".join(tenant_parts))

        # Token count
        if self.total_tokens > 0:
            if self.total_tokens >= 1000:
                token_str = f"{self.total_tokens / 1000:.1f}k"
            else:
                token_str = str(self.total_tokens)
            parts.append(f"Tokens: {token_str}")

        # Cost
        if self.estimated_cost > 0:
            parts.append(f"Cost: ~${self.estimated_cost:.2f}")

        return Text.from_markup(" │ ".join(parts) if parts else "Ready")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_dashboard.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add landlord/dashboard.py tests/test_dashboard.py
git commit -m "feat: add Dashboard with token usage and cost tracking"
```

---

## Task 2: TenantPanel — Rich Panel per Tenant

**Files:**
- Rewrite: `landlord/renderer.py`
- Rewrite: `tests/test_renderer.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from io import StringIO
from collections import deque
from rich.console import Console
from landlord.renderer import TenantPanel, LiveRenderer
from landlord.contract import Contract, Checkpoint
from landlord.dashboard import Dashboard


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
        # Should be a Rich Panel
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_renderer.py -v`
Expected: FAIL (TenantPanel, LiveRenderer not found)

- [ ] **Step 3: Implement LiveRenderer and TenantPanel**

```python
"""Terminal rendering with live tenant panels and status dashboard."""

from __future__ import annotations

from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from landlord.contract import Contract
from landlord.dashboard import Dashboard

BORDER_COLORS = {
    "pending": "dim",
    "running": "blue",
    "waiting": "yellow",
    "complete": "green",
    "failed": "red",
    "escalated": "bold yellow",
}


class TenantPanel:
    """Tracks state and renders a single tenant's panel."""

    def __init__(self, contract: Contract, max_lines: int = 8) -> None:
        self.contract = contract
        self.status = "pending"
        self.lines: deque[str] = deque(maxlen=max_lines)

    def add_line(self, line: str) -> None:
        self.lines.append(line)

    def render(self) -> Panel:
        content = "\n".join(self.lines) if self.lines else "[dim]No activity yet[/dim]"
        title = f"{self.contract.role} ({self.status})"
        return Panel(
            content,
            title=title,
            border_style=BORDER_COLORS.get(self.status, "dim"),
            expand=True,
        )


class LiveRenderer:
    """Renders tenant panels and status dashboard using Rich Live."""

    def __init__(
        self,
        console: Console | None = None,
        dashboard: Dashboard | None = None,
        verbose: bool = False,
    ) -> None:
        self._console = console or Console()
        self._dashboard = dashboard
        self._verbose = verbose
        self._panels: dict[str, TenantPanel] = {}
        self._live: Live | None = None

    def start_live(self) -> None:
        """Enter the Live rendering context."""
        self._live = Live(console=self._console, refresh_per_second=4)
        self._live.start()

    def stop_live(self) -> None:
        """Exit the Live rendering context."""
        if self._live:
            self._live.stop()
            self._live = None

    def _refresh(self) -> None:
        """Rebuild and push the display."""
        if not self._live:
            return
        renderables = [panel.render() for panel in self._panels.values()]
        if self._dashboard:
            renderables.append(self._dashboard.render())
        self._live.update(Group(*renderables))

    # -- Public interface (matches what Landlord calls) --

    def show_plan(self, contracts: list[Contract]) -> None:
        table = Table(title="Execution Plan", show_lines=True)
        table.add_column("Role", style="bold cyan")
        table.add_column("Objective")
        table.add_column("Checkpoints", style="dim")
        table.add_column("Depends On", style="yellow")

        for c in contracts:
            checkpoints = ", ".join(cp.name for cp in c.checkpoints)
            depends = ", ".join(c.depends_on) if c.depends_on else "-"
            table.add_row(c.role, c.objective, checkpoints, depends)

        self._console.print(table)

    def tenant_started(self, contract: Contract) -> None:
        panel = TenantPanel(contract)
        panel.status = "running"
        self._panels[contract.tenant_id] = panel
        if self._dashboard:
            self._dashboard.set_tenant_status(contract.tenant_id, contract.role, "running")
        self._refresh()

    def checkpoint_passed(self, tenant_id: str, checkpoint_name: str) -> None:
        panel = self._panels.get(tenant_id)
        if panel:
            panel.add_line(f"[green]✓[/green] Checkpoint [bold]{checkpoint_name}[/bold] passed")
            self._refresh()

    def checkpoint_failed(self, tenant_id: str, checkpoint_name: str, reason: str) -> None:
        panel = self._panels.get(tenant_id)
        if panel:
            panel.add_line(f"[red]✗[/red] Checkpoint [bold]{checkpoint_name}[/bold] failed: {reason}")
            self._refresh()

    def tenant_evicted(self, tenant_id: str, reason: str) -> None:
        panel = self._panels.get(tenant_id)
        if panel:
            panel.status = "failed"
            panel.add_line(f"[red]! Evicted:[/red] {reason}")
            if self._dashboard:
                self._dashboard.set_tenant_status(tenant_id, panel.contract.role, "failed")
            self._refresh()

    def tenant_completed(self, tenant_id: str) -> None:
        panel = self._panels.get(tenant_id)
        if panel:
            panel.status = "complete"
            panel.add_line("[green]✓ Complete[/green]")
            if self._dashboard:
                self._dashboard.set_tenant_status(tenant_id, panel.contract.role, "complete")
            self._refresh()

    def show_summary(self, results: dict) -> None:
        panel_content = "\n".join(
            f"[cyan]{role}[/cyan]: {status}" for role, status in results.items()
        )
        self._console.print(Panel.fit(panel_content, title="Summary"))

    def stream_token(self, tenant_id: str, token: str) -> None:
        if self._verbose:
            panel = self._panels.get(tenant_id)
            if panel and panel.lines:
                panel.lines[-1] += token
            elif panel:
                panel.add_line(token)
            self._refresh()

    def prompt_approval(self) -> bool:
        response = self._console.input("[bold yellow]Approve this plan? (y/n): [/bold yellow]")
        return response.strip().lower() in ("y", "yes")

    def show_error(self, message: str) -> None:
        self._console.print(f"[bold red]Error:[/bold red] {message}")

    def show_escalation(self, tenant_id: str, role: str) -> None:
        self._console.print(
            f"\n[bold yellow]! Escalation[/bold yellow] Tenant [cyan]{role}[/cyan] "
            f"({tenant_id}) exhausted retries. Manual intervention needed."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_renderer.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add landlord/renderer.py tests/test_renderer.py
git commit -m "feat: rewrite Renderer as LiveRenderer with stacked tenant panels"
```

---

## Task 3: Version String

**Files:**
- Modify: `landlord/__init__.py`

- [ ] **Step 1: Add version**

```python
"""Landlord Framework - An agentic AI framework with contract-based orchestration."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Commit**

```bash
git add landlord/__init__.py
git commit -m "feat: add __version__ to package"
```

---

## Task 4: REPL — Interactive Session Loop

**Files:**
- Create: `landlord/repl.py`
- Create: `tests/test_repl.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from io import StringIO
from rich.console import Console

from landlord.repl import Repl
from landlord.config import LandlordConfig
from landlord.dashboard import Dashboard


class TestRepl:
    @pytest.fixture
    def config(self):
        return LandlordConfig(auto_approve=True)

    @pytest.fixture
    def console_buf(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        return console, buf

    def test_show_welcome(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.show_welcome()
        output = buf.getvalue()
        assert "Landlord Framework" in output
        assert config.landlord_model in output

    def test_handle_help(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.handle_command("/help")
        output = buf.getvalue()
        assert "/help" in output
        assert "/quit" in output

    def test_handle_quit_returns_true(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        result = repl.handle_command("/quit")
        assert result is True  # signals exit

    def test_handle_unknown_command(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        result = repl.handle_command("/bogus")
        assert result is False
        output = buf.getvalue()
        assert "Unknown command" in output

    def test_handle_status_no_run(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.handle_command("/status")
        output = buf.getvalue()
        assert "No tenants" in output or "no run" in output.lower()

    def test_handle_cost_no_run(self, config, console_buf):
        console, buf = console_buf
        repl = Repl(config=config, console=console)
        repl.handle_command("/cost")
        output = buf.getvalue()
        assert "0" in output or "No" in output

    def test_is_command(self, config, console_buf):
        console, _ = console_buf
        repl = Repl(config=config, console=console)
        assert repl.is_command("/help") is True
        assert repl.is_command("Build a REST API") is False
        assert repl.is_command("") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repl.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement Repl**

```python
"""Interactive REPL for the Landlord Framework."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import landlord
from landlord.config import LandlordConfig
from landlord.dashboard import Dashboard


class Repl:
    """Interactive session loop with slash commands."""

    def __init__(
        self,
        config: LandlordConfig,
        console: Console | None = None,
    ) -> None:
        self._config = config
        self._console = console or Console()
        self._dashboard = Dashboard(model=config.landlord_model)
        self._last_contracts: list = []

    @property
    def dashboard(self) -> Dashboard:
        return self._dashboard

    def show_welcome(self) -> None:
        info_parts = [
            f"Model: {self._config.landlord_model}",
            f"Output: {self._config.output_dir}",
            f"Retries: {self._config.max_retries}",
        ]
        info_line = "  │  ".join(info_parts)
        panel = Panel(
            f"  {info_line}  ",
            title=f"Landlord Framework v{landlord.__version__}",
            border_style="bold blue",
        )
        self._console.print(panel)
        self._console.print("  [dim]Tip: Type your task, or /help for commands[/dim]\n")

    def prompt(self) -> str | None:
        """Show the prompt and return user input. Returns None on Ctrl+C/EOF."""
        try:
            return self._console.input("[bold blue]❯[/bold blue] ")
        except (KeyboardInterrupt, EOFError):
            return None

    def is_command(self, text: str) -> bool:
        return text.startswith("/") if text else False

    def handle_command(self, command: str) -> bool:
        """Handle a slash command. Returns True if session should exit."""
        cmd = command.strip().lower()

        if cmd == "/quit":
            self._console.print("[dim]Goodbye.[/dim]")
            return True

        if cmd == "/help":
            self._show_help()
            return False

        if cmd == "/status":
            self._show_status()
            return False

        if cmd == "/cost":
            self._show_cost()
            return False

        if cmd == "/plan":
            self._show_plan()
            return False

        self._console.print(f"[red]Unknown command:[/red] {command}. Type /help for available commands.")
        return False

    def set_last_contracts(self, contracts: list) -> None:
        self._last_contracts = contracts

    def _show_help(self) -> None:
        table = Table(title="Commands", show_header=True, show_lines=False)
        table.add_column("Command", style="bold cyan")
        table.add_column("Description")
        table.add_row("/help", "Show this help")
        table.add_row("/status", "Show tenant statuses from last run")
        table.add_row("/cost", "Show token usage and cost breakdown")
        table.add_row("/plan", "Re-display the last execution plan")
        table.add_row("/quit", "Exit the session")
        self._console.print(table)

    def _show_status(self) -> None:
        statuses = self._dashboard.tenant_statuses
        if not statuses:
            self._console.print("[dim]No tenants — run a task first.[/dim]")
            return
        for _tid, (role, status) in statuses.items():
            self._console.print(f"  {role}: {status}")

    def _show_cost(self) -> None:
        tokens = self._dashboard.total_tokens
        cost = self._dashboard.estimated_cost
        self._console.print(f"  Tokens: {tokens}")
        if cost > 0:
            self._console.print(f"  Estimated cost: ~${cost:.4f}")
        else:
            self._console.print("  [dim]No cost data (unknown model pricing)[/dim]")

    def _show_plan(self) -> None:
        if not self._last_contracts:
            self._console.print("[dim]No plan — run a task first.[/dim]")
            return
        from landlord.renderer import LiveRenderer
        temp = LiveRenderer(console=self._console)
        temp.show_plan(self._last_contracts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repl.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add landlord/repl.py tests/test_repl.py
git commit -m "feat: add REPL with welcome screen and slash commands"
```

---

## Task 5: Wire Up CLI — Interactive + One-Shot Modes

**Files:**
- Rewrite: `landlord/cli.py`
- Rewrite: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock, MagicMock
from landlord.cli import app


runner = CliRunner()


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    @patch("landlord.cli.asyncio.run")
    @patch("landlord.cli.Landlord")
    @patch("landlord.cli.LLMClient")
    @patch("landlord.cli.Validator")
    def test_one_shot_mode(self, mock_val, mock_llm, mock_landlord_cls, mock_run):
        mock_run.side_effect = lambda coro: None
        result = runner.invoke(app, ["Build a REST API"])
        assert result.exit_code == 0

    @patch("landlord.cli.asyncio.run")
    @patch("landlord.cli.Landlord")
    @patch("landlord.cli.LLMClient")
    @patch("landlord.cli.Validator")
    def test_one_shot_with_flags(self, mock_val, mock_llm, mock_landlord_cls, mock_run):
        mock_run.side_effect = lambda coro: None
        result = runner.invoke(app, [
            "Build something",
            "--model", "gpt-4o",
            "--output", "/tmp/out",
            "--verbose",
            "--auto-approve",
        ])
        assert result.exit_code == 0

    @patch("landlord.cli.asyncio.run")
    @patch("landlord.cli.Repl")
    def test_interactive_mode(self, mock_repl_cls, mock_run):
        mock_repl = MagicMock()
        mock_repl_cls.return_value = mock_repl
        mock_run.side_effect = lambda coro: None
        result = runner.invoke(app, [])
        # Should enter interactive mode (no prompt arg)
        assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CLI with dual modes**

```python
"""CLI entry point for the Landlord Framework."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

import typer
from rich.console import Console

from landlord.config import LandlordConfig
from landlord.dashboard import Dashboard
from landlord.event_bus import EventBus
from landlord.llm_client import LLMClient
from landlord.landlord import Landlord
from landlord.renderer import LiveRenderer
from landlord.repl import Repl
from landlord.validator import Validator

app = typer.Typer(
    name="landlord",
    help="An agentic AI framework with contract-based orchestration",
    invoke_without_command=True,
)


def _build_config(
    model: str | None,
    landlord_model: str | None,
    tenant_model: str | None,
    output: str,
    max_retries: int,
    config: str | None,
    verbose: bool,
    auto_approve: bool,
) -> LandlordConfig:
    effective_landlord = landlord_model or model
    effective_tenant = tenant_model or model
    return LandlordConfig.load(
        config_path=config,
        landlord_model=effective_landlord,
        tenant_model=effective_tenant,
        output_dir=output,
        max_retries=max_retries,
        verbose=verbose,
        auto_approve=auto_approve,
    )


def _run_one_shot(cfg: LandlordConfig, prompt: str) -> None:
    """Run a single prompt to completion."""
    dashboard = Dashboard(model=cfg.landlord_model)
    llm_client = LLMClient(model=cfg.landlord_model)
    event_bus = EventBus()
    validator = Validator(llm_client=llm_client)
    renderer = LiveRenderer(dashboard=dashboard, verbose=cfg.verbose)

    landlord = Landlord(
        config=cfg,
        llm_client=llm_client,
        event_bus=event_bus,
        validator=validator,
        renderer=renderer,
    )

    asyncio.run(landlord.run(prompt))


async def _interactive_loop(cfg: LandlordConfig) -> None:
    """Run the interactive REPL."""
    console = Console()
    repl = Repl(config=cfg, console=console)
    repl.show_welcome()

    while True:
        user_input = repl.prompt()
        if user_input is None:
            # Ctrl+C at idle — exit
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if repl.is_command(user_input):
            should_exit = repl.handle_command(user_input)
            if should_exit:
                break
            continue

        # Run a task
        dashboard = repl.dashboard
        llm_client = LLMClient(model=cfg.landlord_model)
        event_bus = EventBus()
        validator = Validator(llm_client=llm_client)
        renderer = LiveRenderer(
            console=console,
            dashboard=dashboard,
            verbose=cfg.verbose,
        )

        landlord = Landlord(
            config=cfg,
            llm_client=llm_client,
            event_bus=event_bus,
            validator=validator,
            renderer=renderer,
        )

        try:
            renderer.start_live()
            results = await landlord.run(user_input)
            renderer.stop_live()
            repl.set_last_contracts(
                list(landlord._active_contracts.values())
            )
            # Update dashboard with token usage
            dashboard.update_tokens(
                prompt_tokens=llm_client.usage.prompt_tokens,
                completion_tokens=llm_client.usage.completion_tokens,
            )
        except KeyboardInterrupt:
            renderer.stop_live()
            console.print("\n[yellow]Interrupted.[/yellow] Returning to prompt.\n")
        except Exception as e:
            renderer.stop_live()
            console.print(f"[red]Error:[/red] {e}\n")


@app.command()
def main(
    prompt: Annotated[Optional[str], typer.Argument(help="The task to accomplish")] = None,
    model: Annotated[Optional[str], typer.Option("--model", "-m", help="Override LLM model")] = None,
    landlord_model: Annotated[Optional[str], typer.Option("--landlord-model")] = None,
    tenant_model: Annotated[Optional[str], typer.Option("--tenant-model")] = None,
    output: Annotated[str, typer.Option("--output", "-o")] = "./output",
    max_retries: Annotated[int, typer.Option("--max-retries")] = 3,
    config: Annotated[Optional[str], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    auto_approve: Annotated[bool, typer.Option("--auto-approve")] = False,
) -> None:
    """Run the Landlord Framework. Pass a prompt for one-shot mode, or omit for interactive."""
    cfg = _build_config(model, landlord_model, tenant_model, output, max_retries, config, verbose, auto_approve)

    if prompt:
        _run_one_shot(cfg, prompt)
    else:
        asyncio.run(_interactive_loop(cfg))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all PASS (may need to update imports in test_landlord.py if Renderer was renamed — the Landlord mocks the renderer interface so it should be fine)

- [ ] **Step 6: Commit**

```bash
git add landlord/cli.py tests/test_cli.py
git commit -m "feat: CLI supports interactive REPL and one-shot modes"
```

---

## Task 6: Integration — Live Rendering During Execution

**Files:**
- Modify: `landlord/landlord.py` (minor: hook token tracking into dashboard)

The Landlord currently creates tenant `LLMClient` instances in `_run_tenant()`. We need to track their tokens in the dashboard. The simplest approach: the LiveRenderer exposes a callback the Landlord can use to report token usage after each tenant completes.

- [ ] **Step 1: Write a test for token reporting**

Add to `tests/test_dashboard.py`:

```python
    def test_multiple_token_updates_accumulate(self, dashboard):
        dashboard.update_tokens(prompt_tokens=100, completion_tokens=50)
        dashboard.update_tokens(prompt_tokens=200, completion_tokens=100)
        assert dashboard.total_tokens == 450
        assert dashboard._prompt_tokens == 300
        assert dashboard._completion_tokens == 150
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS (this should already work from Task 1 implementation)

- [ ] **Step 3: Commit**

```bash
git add tests/test_dashboard.py
git commit -m "test: add accumulation test for dashboard token tracking"
```

---

## Task 7: End-to-End Verification

**Files:** No new files — this is a verification task.

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 2: Run linter**

Run: `ruff check landlord/ tests/`
Expected: all clean

- [ ] **Step 3: Test interactive mode manually**

Run (requires API key):
```bash
python -c "from landlord.cli import app; app([])"
```

Expected: Welcome screen appears with model info, `❯` prompt. Type `/help` to see commands. Type `/quit` to exit.

- [ ] **Step 4: Test one-shot mode still works**

```bash
python -c "from landlord.cli import app; app(['Build a hello world Python script', '--model', 'gpt-4o', '--auto-approve', '-o', './output'])"
```

Expected: Runs to completion with stacked panels.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: end-to-end verification fixes"
```

---

## Verification

After all tasks:

1. `pytest -v` — all pass
2. `ruff check landlord/ tests/` — clean
3. `landlord` (no args) — interactive REPL with welcome, prompt, slash commands
4. `landlord "hello world" --model gpt-4o --auto-approve` — one-shot with stacked panels
5. Ctrl+C during execution — returns to prompt (interactive) or exits (one-shot)
