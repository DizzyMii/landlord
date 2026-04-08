"""Terminal rendering for the Landlord Framework using Rich."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from landlord.contract import Contract


class Renderer:
    """Renders framework status to the terminal."""

    def __init__(self, console: Console | None = None, verbose: bool = False) -> None:
        self._console = console or Console()
        self._verbose = verbose

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
        self._console.print(
            f"[bold green]>[/bold green] Tenant [cyan]{contract.role}[/cyan] "
            f"({contract.tenant_id}) started"
        )

    def checkpoint_passed(self, tenant_id: str, checkpoint_name: str) -> None:
        self._console.print(
            f"  [green]\u2713[/green] [{tenant_id}] Checkpoint [bold]{checkpoint_name}[/bold] passed"
        )

    def checkpoint_failed(self, tenant_id: str, checkpoint_name: str, reason: str) -> None:
        self._console.print(
            f"  [red]\u2717[/red] [{tenant_id}] Checkpoint [bold]{checkpoint_name}[/bold] failed: {reason}"
        )

    def tenant_evicted(self, tenant_id: str, reason: str) -> None:
        self._console.print(
            f"[bold red]! Evicted[/bold red] [{tenant_id}]: {reason}"
        )

    def tenant_completed(self, tenant_id: str) -> None:
        self._console.print(
            f"[bold green]\u2713 Complete[/bold green] [{tenant_id}]"
        )

    def show_summary(self, results: dict) -> None:
        panel = Panel.fit(
            "\n".join(f"[cyan]{role}[/cyan]: {status}" for role, status in results.items()),
            title="Summary",
        )
        self._console.print(panel)

    def stream_token(self, tenant_id: str, token: str) -> None:
        if self._verbose:
            self._console.print(token, end="")

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
