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
    "running": "[green]●[/green]",
    "waiting": "[yellow]●[/yellow]",
    "pending": "[dim]○[/dim]",
    "complete": "[green]✓[/green]",
    "failed": "[red]✗[/red]",
    "escalated": "[bold yellow]⚠[/bold yellow]",
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
        self._tenant_statuses: dict[str, tuple[str, str]] = {}

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

        if self._tenant_statuses:
            tenant_parts = []
            for _tid, (role, status) in self._tenant_statuses.items():
                indicator = STATUS_INDICATORS.get(status, "[dim]?[/dim]")
                tenant_parts.append(f"{indicator} {role}({status})")
            parts.append("Tenants: " + "  ".join(tenant_parts))

        if self.total_tokens > 0:
            if self.total_tokens >= 1000:
                token_str = f"{self.total_tokens / 1000:.1f}k"
            else:
                token_str = str(self.total_tokens)
            parts.append(f"Tokens: {token_str}")

        if self.estimated_cost > 0:
            parts.append(f"Cost: ~${self.estimated_cost:.2f}")

        return Text.from_markup(" │ ".join(parts) if parts else "Ready")
