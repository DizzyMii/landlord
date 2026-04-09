"""Terminal rendering with live tenant panels and status dashboard."""

from __future__ import annotations

from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

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
            panel.add_line(f"[green]\u2713[/green] Checkpoint [bold]{checkpoint_name}[/bold] passed")
            self._refresh()

    def checkpoint_failed(self, tenant_id: str, checkpoint_name: str, reason: str) -> None:
        panel = self._panels.get(tenant_id)
        if panel:
            panel.add_line(f"[red]\u2717[/red] Checkpoint [bold]{checkpoint_name}[/bold] failed: {reason}")
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
            panel.add_line("[green]\u2713 Complete[/green]")
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


# Backward-compatible alias
Renderer = LiveRenderer
