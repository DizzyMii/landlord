"""Live terminal UI for watching a Landlord orchestration.

Reads the events.jsonl + job.json + session.log files produced by the MCP
server and renders a Rich Live dashboard. Runs as a separate process from
the MCP server — no IPC, just tailing files.

    landlord-watch <job_id> [--output-dir DIR] [--refresh 0.5]

Quits on q/Ctrl+C, or automatically when the job reaches a terminal status
(complete, partial, cancelled).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


# Visual language — one place to tune it.
GLYPH = {
    "pending": "○",
    "running": "●",
    "waiting": "◌",
    "complete": "✓",
    "evicted": "✗",
    "escalated": "⚠",
}
BORDER = {
    "pending": "dim",
    "running": "cyan",
    "waiting": "yellow",
    "complete": "green",
    "evicted": "red",
    "escalated": "bold yellow",
    "awaiting_approval": "blue",
    "partial": "yellow",
    "cancelled": "dim",
}
TERMINAL_JOB_STATUSES = {"complete", "partial", "cancelled"}
ACTIVITY_WINDOW = 8
POLL_INTERVAL = 0.5


@dataclass
class TenantView:
    role: str
    tenant_id: str
    status: str = "pending"
    checkpoints_passed: list[str] = field(default_factory=list)
    retry_count: int = 0
    last_error: str | None = None
    activity: deque = field(default_factory=lambda: deque(maxlen=ACTIVITY_WINDOW))

    def log_file(self, job_dir: Path) -> Path:
        return job_dir / self.tenant_id / "session.log"


@dataclass
class JobView:
    job_id: str
    prompt: str = ""
    status: str = "awaiting_approval"
    created_at: float = 0.0
    tenants: dict[str, TenantView] = field(default_factory=dict)

    def elapsed(self) -> str:
        if self.created_at == 0:
            return "—"
        seconds = int(time.time() - self.created_at)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"


# ---------------------------------------------------------------------------
# File tailing — plain, stateless. Each render reads the full events.jsonl
# and replays it to derive view state. That's wasteful at scale but the
# files are tiny (< 1000 events for any realistic job).

def load_events(job_dir: Path) -> list[dict[str, Any]]:
    path = job_dir / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # tolerate mid-write partial line
    return events


def load_job_json(job_dir: Path) -> dict[str, Any] | None:
    path = job_dir / "job.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def tail_session_log(path: Path, n: int = ACTIVITY_WINDOW) -> list[str]:
    """Return the last n meaningful lines from session.log."""
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    # Filter out the noisy wrapper markers the adapter writes.
    filtered = [
        line for line in raw
        if line and not line.startswith("=== ") and not line.startswith("  ")
        or line.startswith("  <")  # keep content-block summaries
    ]
    return filtered[-n:]


# ---------------------------------------------------------------------------
# View construction — pure, testable.

def derive_view(
    job_id: str,
    job_dir: Path,
    job_json: dict[str, Any] | None,
    events: Iterable[dict[str, Any]],
) -> JobView:
    view = JobView(job_id=job_id)

    if job_json:
        view.prompt = job_json.get("prompt", "")
        view.status = job_json.get("status", view.status)
        view.created_at = float(job_json.get("created_at") or 0.0)
        for t in job_json.get("tenants", []):
            role = t.get("role", "?")
            tid = t.get("tenant_id", role)
            view.tenants[tid] = TenantView(
                role=role,
                tenant_id=tid,
                status=t.get("status", "pending"),
                checkpoints_passed=list(t.get("checkpoints_passed", [])),
                retry_count=int(t.get("retry_count", 0)),
                last_error=t.get("last_error"),
            )

    for event in events:
        t = event.get("type", "")
        tid = event.get("tenant_id")
        role = event.get("role")
        if t == "tenant_started" and tid in view.tenants:
            view.tenants[tid].activity.append(
                f"[cyan]▸[/cyan] started"
                + (f" [dim](retry {event.get('retry_count', 0)})[/dim]" if event.get("retry_count") else "")
            )
        elif t == "checkpoint_passed" and tid in view.tenants:
            cp = event.get("checkpoint", "?")
            view.tenants[tid].activity.append(f"[green]✓[/green] {cp}")
        elif t == "checkpoint_failed" and tid in view.tenants:
            cp = event.get("checkpoint", "?")
            reason = event.get("reason", "")
            view.tenants[tid].activity.append(
                f"[red]✗[/red] {cp} [dim]— {reason[:60]}[/dim]"
            )
        elif t == "tenant_retrying" and tid in view.tenants:
            view.tenants[tid].activity.append(
                f"[yellow]↻[/yellow] retrying [dim](#{event.get('retry_count', '?')})[/dim]"
            )
        elif t == "tenant_evicted" and tid in view.tenants:
            reason = event.get("reason", "")
            view.tenants[tid].activity.append(f"[red]evicted[/red] [dim]{reason[:60]}[/dim]")
        elif t == "tenant_escalated" and tid in view.tenants:
            view.tenants[tid].activity.append("[bold yellow]⚠ escalated[/bold yellow]")
        elif t == "tenant_complete" and tid in view.tenants:
            view.tenants[tid].activity.append("[green]complete[/green]")

    return view


# ---------------------------------------------------------------------------
# Rendering.

def render_header(view: JobView) -> Panel:
    status_style = BORDER.get(view.status, "dim")
    title = Text()
    title.append(f" Landlord · job ", style="dim")
    title.append(view.job_id, style="bold")
    title.append("  ·  ", style="dim")
    title.append(view.status, style=status_style)
    title.append("  ·  ", style="dim")
    title.append(view.elapsed(), style="dim")
    title.append(" ")
    body = Text(view.prompt or "(no prompt)", style="bright_white")
    return Panel(body, title=title, border_style=status_style, padding=(1, 2), box=box.ROUNDED)


def render_tenant(tenant: TenantView, job_dir: Path) -> Panel:
    style = BORDER.get(tenant.status, "dim")
    glyph = GLYPH.get(tenant.status, "·")
    ckpts = len(tenant.checkpoints_passed)
    title = Text()
    title.append(f" {tenant.role}  ", style="bold")
    title.append(glyph, style=style)
    title.append(f"  {tenant.status}", style=style)
    if ckpts:
        title.append(f"  ·  {ckpts} ckpts", style="dim")
    if tenant.retry_count:
        title.append(f"  ·  retry {tenant.retry_count}", style="yellow")
    title.append(" ")

    lines: list[str] = list(tenant.activity)
    # Append the last few lines of session.log (SDK chatter) so the user
    # can see what the tenant is actually doing inside the model loop.
    log_tail = tail_session_log(tenant.log_file(job_dir), n=ACTIVITY_WINDOW)
    for line in log_tail[-3:]:
        stripped = line.strip()
        if stripped.startswith("<"):
            lines.append(f"[dim]{stripped[:80]}[/dim]")

    if not lines:
        if tenant.status == "pending":
            body = Text("  waiting for dependencies…", style="dim")
        else:
            body = Text("  no activity yet", style="dim")
        return Panel(body, title=title, border_style=style, padding=(0, 2), box=box.ROUNDED)

    # Dim older lines, normal on the newest. This mirrors Claude Code's
    # fade-out of older turns.
    recent_count = 2
    rendered: list[Text] = []
    for i, line in enumerate(lines[-ACTIVITY_WINDOW:]):
        t = Text.from_markup(f"  {line}")
        if i < len(lines) - recent_count:
            t.stylize("dim")
        rendered.append(t)
    return Panel(Group(*rendered), title=title, border_style=style, padding=(0, 2), box=box.ROUNDED)


def render_status_bar(view: JobView) -> Text:
    parts: list[str] = []
    parts.append(f"job [bold]{view.job_id}[/bold]")
    parts.append(f"[{BORDER.get(view.status, 'dim')}]{view.status}[/]")
    parts.append(f"elapsed [bold]{view.elapsed()}[/bold]")
    tenants_running = sum(1 for t in view.tenants.values() if t.status == "running")
    tenants_total = len(view.tenants)
    parts.append(f"tenants [bold]{tenants_running}/{tenants_total}[/bold]")
    parts.append("[dim]Ctrl+C to quit[/dim]")
    return Text.from_markup("  ·  ".join(parts), justify="center")


def build_renderable(view: JobView, job_dir: Path) -> Group:
    renderables = [render_header(view)]
    for tenant in view.tenants.values():
        renderables.append(render_tenant(tenant, job_dir))
    renderables.append(Text(""))
    renderables.append(render_status_bar(view))
    return Group(*renderables)


# ---------------------------------------------------------------------------
# Entry point.

def _resolve_job_dir(job_id: str, output_dir: Path | None) -> Path:
    if output_dir is not None:
        return output_dir / job_id
    env_dir = os.environ.get("LANDLORD_OUTPUT_DIR")
    base = Path(env_dir).resolve() if env_dir else Path("./landlord-output").resolve()
    return base / job_id


def _wait_for_job_dir(job_dir: Path, timeout: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if job_dir.exists():
            return True
        time.sleep(0.1)
    return False


def run_watch(job_id: str, output_dir: Path | None = None, refresh: float = POLL_INTERVAL) -> int:
    console = Console()
    job_dir = _resolve_job_dir(job_id, output_dir)

    if not _wait_for_job_dir(job_dir, timeout=10):
        console.print(f"[red]No job directory at {job_dir} after 10s.[/red]")
        console.print("[dim]Tip: check the job_id and --output-dir (or $LANDLORD_OUTPUT_DIR).[/dim]")
        return 2

    view_live = Live(console=console, refresh_per_second=4, screen=False)
    view_live.start()
    try:
        while True:
            events = load_events(job_dir)
            job_json = load_job_json(job_dir)
            view = derive_view(job_id, job_dir, job_json, events)
            view_live.update(build_renderable(view, job_dir))
            if view.status in TERMINAL_JOB_STATUSES:
                time.sleep(refresh)
                view = derive_view(job_id, job_dir, load_job_json(job_dir), load_events(job_dir))
                view_live.update(build_renderable(view, job_dir))
                break
            time.sleep(refresh)
    except KeyboardInterrupt:
        pass
    finally:
        view_live.stop()

    console.print()
    console.print(Text.from_markup(
        f"[dim]Final status:[/dim] [{BORDER.get(view.status, 'dim')}]{view.status}[/]  ·  "
        f"[dim]Output:[/dim] {job_dir}"
    ))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="landlord-watch",
        description="Live terminal UI for a Landlord orchestration.",
    )
    parser.add_argument("job_id", help="The job_id returned by start_orchestration.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Base directory containing <job_id>/. Defaults to $LANDLORD_OUTPUT_DIR or ./landlord-output.",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=POLL_INTERVAL,
        help=f"Refresh interval in seconds (default {POLL_INTERVAL}).",
    )
    args = parser.parse_args()
    sys.exit(run_watch(args.job_id, output_dir=args.output_dir, refresh=args.refresh))


if __name__ == "__main__":
    main()
