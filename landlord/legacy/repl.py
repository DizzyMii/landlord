"""Interactive REPL for the Landlord Framework."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import landlord
from landlord.legacy.config import LandlordConfig
from landlord.legacy.dashboard import Dashboard


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
        info_line = "  \u2502  ".join(info_parts)
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
            return self._console.input("[bold blue]\u276f[/bold blue] ")
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
            self._console.print("[dim]No tenants \u2014 run a task first.[/dim]")
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
            self._console.print("[dim]No plan \u2014 run a task first.[/dim]")
            return
        from landlord.legacy.renderer import LiveRenderer
        temp = LiveRenderer(console=self._console)
        temp.show_plan(self._last_contracts)
