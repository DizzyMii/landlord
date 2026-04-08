"""Landlord orchestrator - decomposes prompts and manages tenant execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from landlord.config import LandlordConfig
from landlord.contract import Contract
from landlord.event_bus import Event, EventBus
from landlord.llm_client import LLMClient
from landlord.renderer import Renderer
from landlord.tenant import Tenant
from landlord.tools import get_all_tools
from landlord.validator import ValidationResult, Validator


DECOMPOSE_PROMPT = """You are the Landlord, an AI orchestrator. Decompose the following user request into independent sub-tasks that can be executed by isolated worker agents (tenants).

For each sub-task, provide:
- role: a short role name (e.g., "backend_engineer")
- objective: what this tenant must accomplish
- sub_prompt: the detailed prompt the tenant will receive
- checkpoints: ordered validation points, each with name, description, and a JSON Schema object under "schema"
- output_schema: JSON Schema for the final output
- tools_allowed: tool whitelist (null if unrestricted)
- tools_denied: tool blacklist (null if unrestricted)
- depends_on: list of other role names this tenant needs artifacts from before starting

Return ONLY a JSON array of contract objects. No markdown, no explanation.

User request: {prompt}"""


class Landlord:
    """Orchestrates tenant execution based on user prompts."""

    def __init__(
        self,
        config: LandlordConfig,
        llm_client: LLMClient,
        event_bus: EventBus,
        validator: Validator,
        renderer: Renderer,
    ) -> None:
        self._config = config
        self._llm = llm_client
        self._bus = event_bus
        self._validator = validator
        self._renderer = renderer

        self._active_contracts: dict[str, Contract] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._retry_counts: dict[str, int] = {}
        self._shared_artifacts: dict[str, dict] = {}
        self._dependency_events: dict[str, asyncio.Event] = {}

    async def run(self, prompt: str) -> dict[str, Any]:
        await self._bus.subscribe("checkpoint_reached", self.handle_checkpoint)
        await self._bus.subscribe("task_complete", self._handle_complete)
        await self._bus.subscribe("task_failed", self._handle_failed)

        contracts = await self.decompose(prompt)
        if not contracts:
            self._renderer.show_error("Failed to decompose prompt into tasks.")
            return {}

        self._renderer.show_plan(contracts)
        if not self._config.auto_approve:
            if not self._renderer.prompt_approval():
                return {}

        await self.launch_tenants(contracts)

        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)

        return {
            role: self._shared_artifacts.get(role, {})
            for role in [c.role for c in contracts]
        }

    async def decompose(self, prompt: str) -> list[Contract]:
        messages = [{"role": "user", "content": DECOMPOSE_PROMPT.format(prompt=prompt)}]

        for attempt in range(2):
            response = await self._llm.chat(messages)
            try:
                data = json.loads(response)
                contracts = [Contract(**item) for item in data]
                return contracts
            except (json.JSONDecodeError, Exception) as e:
                if attempt == 0:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": f"That was not valid JSON. Error: {e}. Please return ONLY a JSON array.",
                    })
                else:
                    self._renderer.show_error(f"Failed to parse decomposition: {e}")
                    return []

    async def launch_tenants(self, contracts: list[Contract]) -> None:
        ordered = self._resolve_launch_order(contracts)
        output_base = Path(self._config.output_dir)
        output_base.mkdir(parents=True, exist_ok=True)

        for c in ordered:
            self._dependency_events[c.role] = asyncio.Event()

        for contract in ordered:
            self._active_contracts[contract.tenant_id] = contract
            self._retry_counts[contract.tenant_id] = 0
            task = asyncio.create_task(self._run_tenant(contract, output_base))
            self._active_tasks[contract.tenant_id] = task

    async def _run_tenant(self, contract: Contract, output_base: Path) -> None:
        for dep_role in contract.depends_on:
            if dep_role in self._dependency_events:
                await self._dependency_events[dep_role].wait()

        shared_context = None
        if contract.depends_on:
            parts = []
            for role in contract.depends_on:
                if role in self._shared_artifacts:
                    parts.append(f"## {role}\n{json.dumps(self._shared_artifacts[role], indent=2)}")
            if parts:
                shared_context = "Artifacts from dependencies:\n\n" + "\n\n".join(parts)

        work_dir = output_base / contract.tenant_id
        work_dir.mkdir(parents=True, exist_ok=True)

        tenant_llm = LLMClient(model=self._config.effective_tenant_model)
        all_tools = get_all_tools(work_dir)

        tenant = Tenant(
            contract=contract,
            llm_client=tenant_llm,
            event_bus=self._bus,
            tools=all_tools,
            work_dir=work_dir,
            shared_context=shared_context,
        )

        self._renderer.tenant_started(contract)
        await tenant.run()

    async def handle_checkpoint(self, event: Event) -> None:
        tenant_id = event.tenant_id
        contract = self._active_contracts.get(tenant_id)
        if not contract:
            return

        name = event.payload["name"]
        output = event.payload["output"]
        future = event.payload.get("future")

        checkpoint = next((cp for cp in contract.checkpoints if cp.name == name), None)
        if not checkpoint:
            if future:
                future.set_result(ValidationResult(
                    passed=False, tier=1, explanation=f"Unknown checkpoint: {name}"
                ))
            return

        result = await self._validator.validate_checkpoint(output, checkpoint, contract)

        if result.passed:
            self._renderer.checkpoint_passed(tenant_id, name)
            self._shared_artifacts[contract.role] = output
            if contract.role in self._dependency_events:
                self._dependency_events[contract.role].set()
        else:
            self._renderer.checkpoint_failed(tenant_id, name, result.explanation)

        if future:
            future.set_result(result)

        if not result.passed:
            await self.evict_tenant(tenant_id, result.explanation)

    async def evict_tenant(self, tenant_id: str, reason: str) -> None:
        contract = self._active_contracts.get(tenant_id)
        if not contract:
            return

        task = self._active_tasks.get(tenant_id)
        if task and not task.done():
            task.cancel()

        self._retry_counts[tenant_id] = self._retry_counts.get(tenant_id, 0) + 1
        self._renderer.tenant_evicted(tenant_id, reason)

        if self._retry_counts[tenant_id] >= contract.max_retries:
            self._renderer.show_escalation(tenant_id, contract.role)
            return

        new_contract = contract.model_copy(update={
            "tenant_id": contract.tenant_id,
            "context": f"Previous attempt failed: {reason}. Be more careful to meet requirements.",
        })
        self._active_contracts[tenant_id] = new_contract

        output_base = Path(self._config.output_dir)
        new_task = asyncio.create_task(self._run_tenant(new_contract, output_base))
        self._active_tasks[tenant_id] = new_task

    async def _handle_complete(self, event: Event) -> None:
        tenant_id = event.tenant_id
        contract = self._active_contracts.get(tenant_id)
        if contract:
            self._renderer.tenant_completed(tenant_id)
            if contract.role in self._dependency_events:
                self._dependency_events[contract.role].set()

    async def _handle_failed(self, event: Event) -> None:
        tenant_id = event.tenant_id
        reason = event.payload.get("error", "Unknown error")
        await self.evict_tenant(tenant_id, reason)

    def _resolve_launch_order(self, contracts: list[Contract]) -> list[Contract]:
        by_role: dict[str, Contract] = {c.role: c for c in contracts}
        visited: set[str] = set()
        order: list[Contract] = []

        def visit(role: str) -> None:
            if role in visited:
                return
            visited.add(role)
            contract = by_role.get(role)
            if contract:
                for dep in contract.depends_on:
                    visit(dep)
                order.append(contract)

        for c in contracts:
            visit(c.role)

        return order
