"""The `landlord` CLI — a sleek launcher for orchestration jobs.

Bare `landlord` opens an interactive picker that lists jobs in the active
output directory, lets you pick one (by row number or id prefix), and drops
you into the live watch TUI. Subcommands are available for direct use.

Usage:
    landlord                      # interactive launcher
    landlord ls                   # one-shot list, no prompt
    landlord watch <job_id>       # jump straight to watching a job
    landlord rm <job_id>          # remove a job's output directory
    landlord --output-dir DIR ... # override the search path

The output directory is resolved as: --output-dir > $LANDLORD_OUTPUT_DIR >
./landlord-output (cwd-relative).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


STATUS_STYLE = {
    "awaiting_approval": "blue",
    "running": "cyan",
    "complete": "green",
    "partial": "yellow",
    "cancelled": "dim",
}
TERMINAL = {"complete", "partial", "cancelled"}


@dataclass
class JobSummary:
    job_id: str
    status: str
    prompt: str
    created_at: float
    path: Path
    tenants_total: int
    tenants_done: int


def _default_output_dir() -> Path:
    env = os.environ.get("LANDLORD_OUTPUT_DIR")
    if env:
        return Path(env).resolve()
    return Path("./landlord-output").resolve()


def discover_jobs(output_dir: Path) -> list[JobSummary]:
    """Scan output_dir for job directories, parse each job.json, return summaries."""
    if not output_dir.exists() or not output_dir.is_dir():
        return []
    jobs: list[JobSummary] = []
    for entry in output_dir.iterdir():
        if not entry.is_dir():
            continue
        job_json = entry / "job.json"
        if not job_json.exists():
            continue
        try:
            data = json.loads(job_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        tenants = data.get("tenants", []) or []
        jobs.append(JobSummary(
            job_id=data.get("job_id", entry.name),
            status=data.get("status", "?"),
            prompt=(data.get("prompt") or "").strip(),
            created_at=float(data.get("created_at") or 0.0),
            path=entry,
            tenants_total=len(tenants),
            tenants_done=sum(1 for t in tenants if t.get("status") == "complete"),
        ))
    # Newest first; running/awaiting_approval bubble to the top within their time slot.
    jobs.sort(key=lambda j: (j.status in TERMINAL, -j.created_at))
    return jobs


def _format_age(created_at: float) -> str:
    if created_at == 0:
        return "—"
    delta = max(0, int(time.time() - created_at))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _truncate(text: str, n: int) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def render_jobs_table(console: Console, jobs: list[JobSummary], output_dir: Path) -> None:
    if not jobs:
        console.print()
        console.print(Panel(
            Text.from_markup(
                f"[dim]No jobs found in[/dim] [bold]{output_dir}[/bold]\n\n"
                "[dim]The MCP server writes jobs into the directory it was launched from.[/dim]\n"
                "[dim]To make `landlord` find them from any terminal, set:[/dim]\n"
                f"  [cyan]setx LANDLORD_OUTPUT_DIR \"{output_dir}\"[/cyan]\n"
                "[dim]…or pass [cyan]--output-dir <path>[/cyan] explicitly.[/dim]"
            ),
            border_style="dim",
            box=box.ROUNDED,
            padding=(1, 2),
        ))
        return

    table = Table(
        title=f"  Landlord jobs in [bold]{output_dir}[/bold]",
        title_justify="left",
        box=box.ROUNDED,
        border_style="dim",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("id", style="bold", width=10)
    table.add_column("status", width=18)
    table.add_column("tenants", width=8, justify="right")
    table.add_column("age", style="dim", width=10)
    table.add_column("prompt", overflow="ellipsis", no_wrap=True)

    for i, job in enumerate(jobs, start=1):
        style = STATUS_STYLE.get(job.status, "dim")
        status_cell = Text.from_markup(f"[{style}]{job.status}[/]")
        tenants_cell = f"{job.tenants_done}/{job.tenants_total}" if job.tenants_total else "—"
        table.add_row(
            str(i),
            job.job_id,
            status_cell,
            tenants_cell,
            _format_age(job.created_at),
            _truncate(job.prompt, 80),
        )
    console.print()
    console.print(table)


def resolve_selection(selection: str, jobs: list[JobSummary]) -> JobSummary | None:
    """Resolve a user input string to a single job, or None if not matched."""
    sel = selection.strip()
    if not sel:
        return None
    if sel.isdigit():
        n = int(sel)
        if 1 <= n <= len(jobs):
            return jobs[n - 1]
        return None
    matches = [j for j in jobs if j.job_id.startswith(sel)]
    if len(matches) == 1:
        return matches[0]
    return None


def _open_watch(job: JobSummary, output_dir: Path) -> int:
    """Drop into the live watch UI for the given job. Imports inside to keep
    `landlord ls` cheap (Rich Live spins up a thread)."""
    from landlord.watch import run_watch
    return run_watch(job.job_id, output_dir=output_dir)


def cmd_ls(args: argparse.Namespace) -> int:
    console = Console()
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    jobs = discover_jobs(output_dir)
    render_jobs_table(console, jobs, output_dir)
    return 0 if jobs else 1


def cmd_watch(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    from landlord.watch import run_watch
    return run_watch(args.job_id, output_dir=output_dir)


def cmd_rm(args: argparse.Namespace) -> int:
    console = Console()
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    target = output_dir / args.job_id
    if not target.exists():
        console.print(f"[red]No job at {target}[/red]")
        return 2
    shutil.rmtree(target)
    console.print(f"[dim]Removed[/dim] {target}")
    return 0


def cmd_default(args: argparse.Namespace) -> int:
    """Interactive launcher: list jobs, prompt for selection, drop into watch."""
    console = Console()
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    jobs = discover_jobs(output_dir)
    render_jobs_table(console, jobs, output_dir)
    if not jobs:
        return 1
    console.print()
    try:
        raw = console.input(
            "[bold]Select[/bold] [dim]row #, id prefix, or[/dim] [bold]q[/bold] [dim]to quit:[/dim] "
        )
    except (EOFError, KeyboardInterrupt):
        console.print()
        return 0
    if raw.strip().lower() in ("", "q", "quit", "exit"):
        return 0
    job = resolve_selection(raw, jobs)
    if job is None:
        console.print(f"[red]No match for '{raw.strip()}'.[/red] [dim]Use a row number or job-id prefix.[/dim]")
        return 2
    return _open_watch(job, output_dir)


def _add_output_dir(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Job output directory. Defaults to $LANDLORD_OUTPUT_DIR or ./landlord-output.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="landlord",
        description="Landlord orchestration CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_output_dir(parser)
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    p_ls = sub.add_parser("ls", help="List jobs as a table (no prompt).")
    _add_output_dir(p_ls)
    p_ls.set_defaults(func=cmd_ls)

    p_watch = sub.add_parser("watch", help="Watch a specific job in the live TUI.")
    _add_output_dir(p_watch)
    p_watch.add_argument("job_id", help="Job id (full or prefix).")
    p_watch.set_defaults(func=cmd_watch)

    p_rm = sub.add_parser("rm", help="Remove a job's output directory.")
    _add_output_dir(p_rm)
    p_rm.add_argument("job_id", help="Job id (full).")
    p_rm.set_defaults(func=cmd_rm)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    func = getattr(args, "func", cmd_default)
    sys.exit(func(args))


if __name__ == "__main__":
    main()
