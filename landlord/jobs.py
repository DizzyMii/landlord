"""In-memory job registry with JSON sidecar persistence."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from landlord.contract import Contract


JobStatus = str  # "awaiting_approval" | "running" | "complete" | "partial" | "cancelled"
TenantStatusLiteral = str  # "pending" | "running" | "complete" | "evicted" | "escalated"


class UnknownJobError(KeyError):
    """Raised when a job_id has no entry in the registry."""


@dataclass
class TenantState:
    contract: Contract
    status: TenantStatusLiteral = "pending"
    checkpoints_passed: list[str] = field(default_factory=list)
    retry_count: int = 0
    last_error: str | None = None
    task: asyncio.Task | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.contract.role,
            "tenant_id": self.contract.tenant_id,
            "status": self.status,
            "checkpoints_passed": list(self.checkpoints_passed),
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }


@dataclass
class Job:
    job_id: str
    prompt: str
    plan: list[Contract]
    output_dir: Path
    status: JobStatus = "awaiting_approval"
    tenants: dict[str, TenantState] = field(default_factory=dict)
    artifacts: dict[str, dict] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None

    @classmethod
    def create(cls, prompt: str, plan: list[Contract], output_dir: Path) -> Job:
        job_id = uuid4().hex[:8]
        job_dir = output_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "shared").mkdir(exist_ok=True)
        tenants = {c.tenant_id: TenantState(contract=c) for c in plan}
        return cls(
            job_id=job_id,
            prompt=prompt,
            plan=list(plan),
            output_dir=job_dir,
            tenants=tenants,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "prompt": self.prompt,
            "status": self.status,
            "plan": [c.model_dump() for c in self.plan],
            "tenants": [t.to_dict() for t in self.tenants.values()],
            "artifacts": dict(self.artifacts),
            "created_at": self.created_at,
            "approved_at": self.approved_at,
        }

    def write_sidecar(self) -> None:
        (self.output_dir / "job.json").write_text(
            json.dumps(self.to_dict(), indent=2, default=str)
        )


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    def _get_or_raise(self, job_id: str) -> Job:
        """Lookup job by id or raise UnknownJobError. Caller must hold _lock."""
        job = self._jobs.get(job_id)
        if job is None:
            raise UnknownJobError(job_id)
        return job

    async def create_job(self, prompt: str, plan: list[Contract], output_dir: Path) -> Job:
        job = Job.create(prompt=prompt, plan=plan, output_dir=output_dir)
        async with self._lock:
            self._jobs[job.job_id] = job
            job.write_sidecar()
        return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def transition(self, job_id: str, new_status: JobStatus) -> Job:
        async with self._lock:
            job = self._get_or_raise(job_id)
            job.status = new_status
            if new_status == "running" and job.approved_at is None:
                job.approved_at = time.time()
            job.write_sidecar()
        return job

    async def replace_plan(self, job_id: str, new_plan: list[Contract]) -> Job:
        async with self._lock:
            job = self._get_or_raise(job_id)
            job.plan = list(new_plan)
            job.tenants = {c.tenant_id: TenantState(contract=c) for c in new_plan}
            job.write_sidecar()
        return job

    def all_ids(self) -> list[str]:
        return list(self._jobs.keys())
