"""Tests for the `landlord` CLI launcher."""
from __future__ import annotations

import json
import time
from pathlib import Path

from rich.console import Console

from landlord.cli import (
    JobSummary,
    discover_jobs,
    render_jobs_table,
    resolve_selection,
)


def _seed_job(output_dir: Path, job_id: str, status: str, prompt: str, age_seconds: float = 0, tenants_total: int = 1, tenants_done: int = 0):
    job_dir = output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    tenants = []
    for i in range(tenants_total):
        tenants.append({
            "role": f"role{i}",
            "tenant_id": f"t-{i}",
            "status": "complete" if i < tenants_done else "running",
            "checkpoints_passed": [],
            "retry_count": 0,
            "last_error": None,
        })
    (job_dir / "job.json").write_text(json.dumps({
        "job_id": job_id,
        "prompt": prompt,
        "status": status,
        "created_at": time.time() - age_seconds,
        "tenants": tenants,
    }))
    return job_dir


def test_discover_jobs_returns_empty_for_missing_dir(tmp_path: Path):
    assert discover_jobs(tmp_path / "nope") == []


def test_discover_jobs_returns_empty_for_dir_without_jobs(tmp_path: Path):
    assert discover_jobs(tmp_path) == []


def test_discover_jobs_skips_dirs_without_job_json(tmp_path: Path):
    (tmp_path / "not_a_job").mkdir()
    assert discover_jobs(tmp_path) == []


def test_discover_jobs_skips_corrupt_job_json(tmp_path: Path):
    job_dir = tmp_path / "abc12345"
    job_dir.mkdir()
    (job_dir / "job.json").write_text("not valid json {{")
    assert discover_jobs(tmp_path) == []


def test_discover_jobs_parses_metadata(tmp_path: Path):
    _seed_job(tmp_path, "abc12345", "complete", "build a thing", age_seconds=10)
    jobs = discover_jobs(tmp_path)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_id == "abc12345"
    assert j.status == "complete"
    assert j.prompt == "build a thing"
    assert j.tenants_total == 1


def test_discover_jobs_sorts_running_before_terminal(tmp_path: Path):
    _seed_job(tmp_path, "old00000", "complete", "old", age_seconds=1000)
    _seed_job(tmp_path, "newrun00", "running", "new", age_seconds=10)
    _seed_job(tmp_path, "oldrun00", "running", "older running", age_seconds=500)
    jobs = discover_jobs(tmp_path)
    # Running jobs (newrun + oldrun) before terminal (old). Within each group, newer first.
    statuses = [j.status for j in jobs]
    assert statuses == ["running", "running", "complete"]
    # newer running first
    assert jobs[0].job_id == "newrun00"
    assert jobs[1].job_id == "oldrun00"


def test_resolve_selection_by_row_number():
    jobs = [
        JobSummary("aaa11111", "running", "a", 0, Path("."), 1, 0),
        JobSummary("bbb22222", "complete", "b", 0, Path("."), 1, 1),
    ]
    assert resolve_selection("1", jobs) is jobs[0]
    assert resolve_selection("2", jobs) is jobs[1]
    assert resolve_selection("3", jobs) is None
    assert resolve_selection("0", jobs) is None


def test_resolve_selection_by_id_prefix():
    jobs = [
        JobSummary("aaa11111", "running", "a", 0, Path("."), 1, 0),
        JobSummary("bbb22222", "complete", "b", 0, Path("."), 1, 1),
    ]
    assert resolve_selection("aaa", jobs) is jobs[0]
    assert resolve_selection("bbb22", jobs) is jobs[1]


def test_resolve_selection_rejects_ambiguous_prefix():
    jobs = [
        JobSummary("abc11111", "running", "a", 0, Path("."), 1, 0),
        JobSummary("abc22222", "complete", "b", 0, Path("."), 1, 1),
    ]
    # both start with "abc" — should refuse to guess
    assert resolve_selection("abc", jobs) is None


def test_resolve_selection_rejects_no_match():
    jobs = [JobSummary("aaa11111", "running", "a", 0, Path("."), 1, 0)]
    assert resolve_selection("zzz", jobs) is None


def test_resolve_selection_rejects_empty():
    jobs = [JobSummary("aaa11111", "running", "a", 0, Path("."), 1, 0)]
    assert resolve_selection("", jobs) is None


def test_render_jobs_table_empty_includes_setx_hint(tmp_path: Path):
    console = Console(record=True, width=120)
    render_jobs_table(console, [], tmp_path)
    output = console.export_text()
    assert "No jobs found" in output
    assert "LANDLORD_OUTPUT_DIR" in output


def test_render_jobs_table_shows_columns(tmp_path: Path):
    _seed_job(tmp_path, "abc12345", "complete", "do a thing with words", age_seconds=30, tenants_total=2, tenants_done=2)
    _seed_job(tmp_path, "def67890", "running", "do another thing", age_seconds=5, tenants_total=3, tenants_done=1)
    jobs = discover_jobs(tmp_path)
    console = Console(record=True, width=120)
    render_jobs_table(console, jobs, tmp_path)
    output = console.export_text()
    # Both job ids appear
    assert "abc12345" in output
    assert "def67890" in output
    # Status text appears
    assert "complete" in output
    assert "running" in output
    # Tenants column shows count
    assert "2/2" in output
    assert "1/3" in output
    # Prompts appear (truncated if needed)
    assert "do a thing with words" in output
    assert "do another thing" in output
