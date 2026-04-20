"""Tests for the live watch TUI's pure functions."""
from __future__ import annotations

import json
import time
from pathlib import Path

from rich.console import Console

from landlord.watch import (
    build_renderable,
    derive_view,
    load_events,
    load_job_json,
    render_header,
    render_tenant,
    tail_session_log,
)


def _seed_job_dir(tmp_path: Path) -> Path:
    job_dir = tmp_path / "abc12345"
    job_dir.mkdir()
    (job_dir / "shared").mkdir()
    (job_dir / "t-backend").mkdir()
    (job_dir / "t-frontend").mkdir()

    now = time.time()
    (job_dir / "job.json").write_text(json.dumps({
        "job_id": "abc12345",
        "prompt": "build a tiny todo app",
        "status": "running",
        "created_at": now - 90,
        "approved_at": now - 80,
        "tenants": [
            {
                "role": "backend",
                "tenant_id": "t-backend",
                "status": "complete",
                "checkpoints_passed": ["api_ready"],
                "retry_count": 0,
                "last_error": None,
            },
            {
                "role": "frontend",
                "tenant_id": "t-frontend",
                "status": "running",
                "checkpoints_passed": [],
                "retry_count": 1,
                "last_error": "first attempt failed",
            },
        ],
    }))

    events = [
        {"ts": now - 90, "type": "job_created", "job_id": "abc12345", "prompt": "build a tiny todo app"},
        {"ts": now - 80, "type": "plan_approved", "job_id": "abc12345"},
        {"ts": now - 75, "type": "tenant_started", "job_id": "abc12345", "tenant_id": "t-backend", "role": "backend"},
        {"ts": now - 40, "type": "checkpoint_passed", "job_id": "abc12345", "tenant_id": "t-backend", "role": "backend", "checkpoint": "api_ready"},
        {"ts": now - 38, "type": "tenant_complete", "job_id": "abc12345", "tenant_id": "t-backend", "role": "backend"},
        {"ts": now - 37, "type": "tenant_started", "job_id": "abc12345", "tenant_id": "t-frontend", "role": "frontend"},
        {"ts": now - 20, "type": "checkpoint_failed", "job_id": "abc12345", "tenant_id": "t-frontend", "role": "frontend", "checkpoint": "ui_ready", "reason": "render test did not match snapshot"},
        {"ts": now - 18, "type": "tenant_retrying", "job_id": "abc12345", "tenant_id": "t-frontend", "role": "frontend", "retry_count": 1},
    ]
    (job_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    (job_dir / "t-backend" / "session.log").write_text(
        "=== tenant session start ===\n"
        "[AssistantMessage]\n"
        "  <TextBlock> Writing routes...\n"
        "[AssistantMessage]\n"
        "  <ToolUseBlock> tool=Write input={'file_path': 'src/routes.py'}\n"
    )

    return job_dir


def test_load_events_tolerates_empty(tmp_path: Path):
    assert load_events(tmp_path / "abc") == []


def test_load_events_parses_valid_lines(tmp_path: Path):
    job_dir = _seed_job_dir(tmp_path)
    events = load_events(job_dir)
    assert len(events) == 8
    assert events[0]["type"] == "job_created"
    assert events[-1]["type"] == "tenant_retrying"


def test_load_events_tolerates_partial_final_line(tmp_path: Path):
    job_dir = tmp_path / "x"
    job_dir.mkdir()
    (job_dir / "events.jsonl").write_text(
        '{"type": "a", "job_id": "x"}\n{"type": "b", "job_id": "x"}\n{"incomplete'
    )
    events = load_events(job_dir)
    assert [e["type"] for e in events] == ["a", "b"]


def test_load_job_json(tmp_path: Path):
    job_dir = _seed_job_dir(tmp_path)
    data = load_job_json(job_dir)
    assert data is not None
    assert data["job_id"] == "abc12345"
    assert data["status"] == "running"


def test_derive_view_seeds_tenants_from_job_json(tmp_path: Path):
    job_dir = _seed_job_dir(tmp_path)
    view = derive_view(
        job_id="abc12345",
        job_dir=job_dir,
        job_json=load_job_json(job_dir),
        events=load_events(job_dir),
    )
    assert view.status == "running"
    assert view.prompt == "build a tiny todo app"
    assert set(t.role for t in view.tenants.values()) == {"backend", "frontend"}
    backend = next(t for t in view.tenants.values() if t.role == "backend")
    assert backend.status == "complete"
    assert backend.checkpoints_passed == ["api_ready"]
    # Activity was populated from events.
    activity_text = "\n".join(backend.activity)
    assert "api_ready" in activity_text
    assert "complete" in activity_text


def test_derive_view_includes_failed_checkpoint_reason(tmp_path: Path):
    job_dir = _seed_job_dir(tmp_path)
    view = derive_view(
        job_id="abc12345",
        job_dir=job_dir,
        job_json=load_job_json(job_dir),
        events=load_events(job_dir),
    )
    frontend = next(t for t in view.tenants.values() if t.role == "frontend")
    activity_text = "\n".join(frontend.activity)
    assert "ui_ready" in activity_text
    assert "snapshot" in activity_text
    assert "retrying" in activity_text


def test_tail_session_log_returns_meaningful_lines(tmp_path: Path):
    job_dir = _seed_job_dir(tmp_path)
    log_path = job_dir / "t-backend" / "session.log"
    tail = tail_session_log(log_path, n=10)
    # Should keep the content-block lines (those start with "  <"), drop wrapper lines.
    assert any("TextBlock" in line for line in tail)
    assert any("ToolUseBlock" in line for line in tail)
    # Wrapper lines stripped.
    assert not any(line.startswith("=== ") for line in tail)


def test_build_renderable_does_not_crash(tmp_path: Path):
    """Smoke-render everything to a headless Console and make sure it doesn't throw."""
    job_dir = _seed_job_dir(tmp_path)
    view = derive_view(
        job_id="abc12345",
        job_dir=job_dir,
        job_json=load_job_json(job_dir),
        events=load_events(job_dir),
    )
    renderable = build_renderable(view, job_dir)
    console = Console(record=True, width=100)
    console.print(renderable)
    output = console.export_text()
    assert "abc12345" in output
    assert "backend" in output
    assert "frontend" in output
    assert "build a tiny todo app" in output


def test_render_header_shows_status_and_elapsed(tmp_path: Path):
    job_dir = _seed_job_dir(tmp_path)
    view = derive_view(
        job_id="abc12345",
        job_dir=job_dir,
        job_json=load_job_json(job_dir),
        events=[],
    )
    console = Console(record=True, width=100)
    console.print(render_header(view))
    output = console.export_text()
    assert "abc12345" in output
    assert "running" in output


def test_render_tenant_waiting_case(tmp_path: Path):
    from landlord.watch import TenantView
    tenant = TenantView(role="frontend", tenant_id="t-f", status="pending")
    console = Console(record=True, width=80)
    console.print(render_tenant(tenant, tmp_path))
    output = console.export_text()
    assert "frontend" in output
    assert "pending" in output
    assert "waiting" in output
