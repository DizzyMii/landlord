"""Landlord orchestrator — decomposes prompts, launches tenants, handles eviction."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from landlord.agent_sdk_client import AgentSDKClient
from landlord.contract import Checkpoint, Contract
from landlord.jobs import Job, JobRegistry, TenantState
from landlord.tenant import CheckpointVerdict, TenantRunner
from landlord.validator import Validator


class DependencyCycleError(ValueError):
    """Raised when a plan's depends_on graph contains a cycle."""


def resolve_launch_order(plan: list[Contract]) -> list[Contract]:
    """Topologically sort contracts by depends_on. Raises on cycles."""
    by_role: dict[str, Contract] = {c.role: c for c in plan}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {c.role: WHITE for c in plan}
    order: list[Contract] = []

    def visit(role: str, stack: list[str]) -> None:
        if color.get(role) == GRAY:
            cycle = " -> ".join(stack + [role])
            raise DependencyCycleError(f"Dependency cycle: {cycle}")
        if color.get(role) == BLACK:
            return
        if role not in by_role:
            return
        color[role] = GRAY
        for dep in by_role[role].depends_on:
            visit(dep, stack + [role])
        color[role] = BLACK
        order.append(by_role[role])

    for c in plan:
        visit(c.role, [])
    return order


DECOMPOSE_SYSTEM = (
    "You are the Landlord, an agentic orchestrator. Given a user request, decompose it "
    "into independent sub-tasks that can be executed by isolated worker agents (tenants) "
    "in parallel where possible. For each tenant, return a contract with: role (short "
    "name), objective, sub_prompt (what the tenant receives), checkpoints (list of "
    "{name, description, schema} - schemas MUST be lenient JSON Schemas with a required "
    "property; no enum/const/pattern/minItems), output_schema, and depends_on (list of "
    "roles whose checkpoints this tenant needs before it can start). Keep the plan as "
    "small as it can reasonably be; avoid over-decomposition. Call the `emit_plan` tool "
    "with the contracts array."
)

DECOMPOSE_TOOL: dict[str, Any] = {
    "name": "emit_plan",
    "description": "Return the decomposed plan as a list of Contract objects.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contracts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "objective": {"type": "string"},
                        "sub_prompt": {"type": "string"},
                        "checkpoints": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "schema": {"type": "object"},
                                },
                                "required": ["name", "description", "schema"],
                            },
                        },
                        "output_schema": {"type": "object"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["role", "objective", "sub_prompt", "checkpoints", "output_schema"],
                },
            }
        },
        "required": ["contracts"],
    },
}


@dataclass
class OrchestratorConfig:
    landlord_model: str = "claude-opus-4-7"
    tenant_model: str = "claude-sonnet-4-6"
    default_max_retries: int = 3

    @classmethod
    def from_env(cls) -> OrchestratorConfig:
        return cls(
            landlord_model=os.environ.get("LANDLORD_LANDLORD_MODEL", "claude-opus-4-7"),
            tenant_model=os.environ.get("LANDLORD_TENANT_MODEL", "claude-sonnet-4-6"),
            default_max_retries=int(os.environ.get("LANDLORD_MAX_RETRIES", "3")),
        )


class Landlord:
    def __init__(
        self,
        config: OrchestratorConfig,
        registry: JobRegistry,
        client: AgentSDKClient,
        validator: Validator,
        sdk_session_factory: Callable[..., Any],
    ) -> None:
        self._config = config
        self._registry = registry
        self._client = client
        self._validator = validator
        self._sdk_factory = sdk_session_factory

    async def decompose(self, prompt: str) -> list[Contract]:
        verdict = await self._client.call_forced_tool(
            system=DECOMPOSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tool=DECOMPOSE_TOOL,
        )
        raw_contracts = verdict.get("contracts", [])
        contracts: list[Contract] = []
        for raw in raw_contracts:
            raw.setdefault("depends_on", [])
            raw.setdefault("max_retries", self._config.default_max_retries)
            contracts.append(Contract(**raw))
        resolve_launch_order(contracts)
        return contracts

    async def launch(self, job: Job) -> None:
        """Spawn all tenant tasks. Returns immediately; tasks run in background."""
        dep_events: dict[str, asyncio.Event] = {c.role: asyncio.Event() for c in job.plan}
        order = resolve_launch_order(job.plan)
        for contract in order:
            tenant_state = job.tenants[contract.tenant_id]
            task = asyncio.create_task(self._run_tenant(job, tenant_state, dep_events))
            tenant_state.task = task

    async def wait_until_done(self, job: Job) -> None:
        tasks = [t.task for t in job.tenants.values() if t.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        all_complete = all(t.status == "complete" for t in job.tenants.values())
        new_status = "complete" if all_complete else "partial"
        await self._registry.transition(job.job_id, new_status)
        job.emit_event(f"job_{new_status}")

    async def _run_tenant(
        self,
        job: Job,
        tenant_state: TenantState,
        dep_events: dict[str, asyncio.Event],
    ) -> None:
        contract = tenant_state.contract
        for dep_role in contract.depends_on:
            if dep_role in dep_events:
                await dep_events[dep_role].wait()

        shared_context = self._build_shared_context(job, contract)
        retry_context: str | None = tenant_state.last_error

        work_dir = job.output_dir / contract.tenant_id
        work_dir.mkdir(parents=True, exist_ok=True)

        tenant_state.status = "running"
        job.write_sidecar()
        job.emit_event(
            "tenant_started",
            tenant_id=contract.tenant_id,
            role=contract.role,
            retry_count=tenant_state.retry_count,
        )

        async def checkpoint_handler(cp_name: str, args: dict[str, Any]) -> CheckpointVerdict:
            checkpoint = next(
                (cp for cp in contract.checkpoints if cp.name == cp_name),
                None,
            )
            if checkpoint is None:
                reason = f"Unknown checkpoint {cp_name}"
                tenant_state.last_error = reason
                return CheckpointVerdict(passed=False, reason=reason)
            result = await self._validator.validate_checkpoint(
                output=args, checkpoint=checkpoint, contract=contract
            )
            if result.passed:
                tenant_state.checkpoints_passed.append(cp_name)
                job.artifacts[contract.role] = args
                shared_path = job.output_dir / "shared" / f"{contract.role}.json"
                shared_path.write_text(json.dumps(args, indent=2, default=str))
                dep_events[contract.role].set()
                job.write_sidecar()
                job.emit_event(
                    "checkpoint_passed",
                    tenant_id=contract.tenant_id,
                    role=contract.role,
                    checkpoint=cp_name,
                )
                return CheckpointVerdict(passed=True, reason=result.explanation)
            # Record the most recent failure so retries get fresh retry_context.
            tenant_state.last_error = f"Checkpoint '{cp_name}' failed: {result.explanation}"
            job.emit_event(
                "checkpoint_failed",
                tenant_id=contract.tenant_id,
                role=contract.role,
                checkpoint=cp_name,
                reason=result.explanation,
            )
            return CheckpointVerdict(passed=False, reason=result.explanation)

        runner = TenantRunner(
            contract=contract,
            work_dir=work_dir,
            checkpoint_handler=checkpoint_handler,
            sdk_session_factory=self._sdk_factory,
            model=self._config.tenant_model,
            shared_context=shared_context,
            retry_context=retry_context,
        )

        try:
            tenant_result = await runner.run()
        except Exception as e:
            tenant_state.status = "evicted"
            tenant_state.last_error = f"unexpected error: {e}"
            job.emit_event(
                "tenant_evicted",
                tenant_id=contract.tenant_id,
                role=contract.role,
                reason=tenant_state.last_error,
            )
            await self._maybe_retry(job, tenant_state, dep_events)
            return

        required_checkpoint_names = {cp.name for cp in contract.checkpoints}
        passed = set(tenant_state.checkpoints_passed)
        if required_checkpoint_names - passed:
            tenant_state.status = "evicted"
            if tenant_state.last_error is None:
                tenant_state.last_error = "tenant finished without passing all checkpoints"
            job.emit_event(
                "tenant_evicted",
                tenant_id=contract.tenant_id,
                role=contract.role,
                reason=tenant_state.last_error,
            )
            await self._maybe_retry(job, tenant_state, dep_events)
            return

        tenant_state.status = "complete"
        job.write_sidecar()
        job.emit_event(
            "tenant_complete",
            tenant_id=contract.tenant_id,
            role=contract.role,
        )

    async def _maybe_retry(
        self,
        job: Job,
        tenant_state: TenantState,
        dep_events: dict[str, asyncio.Event],
    ) -> None:
        contract = tenant_state.contract
        tenant_state.retry_count += 1
        if tenant_state.retry_count >= contract.max_retries:
            tenant_state.status = "escalated"
            job.write_sidecar()
            job.emit_event(
                "tenant_escalated",
                tenant_id=contract.tenant_id,
                role=contract.role,
                retry_count=tenant_state.retry_count,
                last_error=tenant_state.last_error,
            )
            return
        tenant_state.checkpoints_passed = []
        tenant_state.status = "pending"
        job.write_sidecar()
        job.emit_event(
            "tenant_retrying",
            tenant_id=contract.tenant_id,
            role=contract.role,
            retry_count=tenant_state.retry_count,
            last_error=tenant_state.last_error,
        )
        task = asyncio.create_task(self._run_tenant(job, tenant_state, dep_events))
        tenant_state.task = task

    def _build_shared_context(self, job: Job, contract: Contract) -> str | None:
        if not contract.depends_on:
            return None
        parts = []
        for dep_role in contract.depends_on:
            if dep_role in job.artifacts:
                parts.append(
                    f"## {dep_role}\n"
                    f"Artifact also available at shared/{dep_role}.json\n"
                    f"{json.dumps(job.artifacts[dep_role], indent=2, default=str)}"
                )
        if not parts:
            return None
        return "Artifacts from dependencies:\n\n" + "\n\n".join(parts)
