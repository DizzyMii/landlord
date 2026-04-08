# Tenant Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Tenant async worker that runs an LLM conversation loop, dispatches tool calls, emits checkpoint events, and blocks on validation.

**Architecture:** Tenant receives a Contract, LLMClient, EventBus, tools dict, and work_dir. It runs a while-True loop calling chat_with_tools, dispatching tool calls (including the pseudo-tool emit_checkpoint internally), and publishing events (checkpoint_reached, task_complete, task_failed). Checkpoints block via asyncio.Future resolved externally by the Landlord.

**Tech Stack:** Python 3.11+, asyncio, pydantic, pytest, pytest-asyncio

---

### Task 1: Write tests/test_tenant.py (all tests, expect failures)

**Files:**
- Create: `tests/test_tenant.py`

- [ ] **Step 1: Write the full test file**

```python
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from landlord.tenant import Tenant
from landlord.contract import Contract, Checkpoint
from landlord.event_bus import EventBus, Event
from landlord.llm_client import LLMClient
from landlord.tools.base import ToolResult


def make_contract(**overrides):
    defaults = dict(
        role="test_worker",
        objective="Do a test task",
        sub_prompt="Complete this test task.",
        checkpoints=[
            Checkpoint(name="step1", description="First step done", schema={"type": "object"})
        ],
        output_schema={"type": "object"},
    )
    defaults.update(overrides)
    return Contract(**defaults)


def make_text_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.choices[0].message.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


def make_tool_call_response(name: str, arguments: dict, call_id: str = "call_1"):
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = None
    resp.choices[0].message.tool_calls = [tool_call]
    resp.choices[0].message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}],
    }
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


class TestTenant:
    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def mock_llm(self):
        return MagicMock(spec=LLMClient)

    async def test_simple_conversation_completes(self, bus, mock_llm, tmp_work_dir):
        mock_llm.chat_with_tools = AsyncMock(return_value=make_text_response("Done!"))
        contract = make_contract()

        events = []
        async def capture(event: Event):
            events.append(event)
        await bus.subscribe("task_complete", capture)

        tenant = Tenant(
            contract=contract, llm_client=mock_llm, event_bus=bus,
            tools={}, work_dir=tmp_work_dir,
        )
        await tenant.run()
        assert any(e.event_type == "task_complete" for e in events)

    async def test_tool_call_executes(self, bus, mock_llm, tmp_work_dir):
        mock_tool = MagicMock()
        mock_tool.name = "file_write"
        mock_tool.execute = AsyncMock(return_value=ToolResult(success=True, output="Written"))

        mock_llm.chat_with_tools = AsyncMock(side_effect=[
            make_tool_call_response("file_write", {"path": "test.txt", "content": "hi"}),
            make_text_response("All done!"),
        ])

        contract = make_contract()
        tenant = Tenant(
            contract=contract, llm_client=mock_llm, event_bus=bus,
            tools={"file_write": mock_tool}, work_dir=tmp_work_dir,
        )
        await tenant.run()
        mock_tool.execute.assert_called_once()

    async def test_checkpoint_emits_event(self, bus, mock_llm, tmp_work_dir):
        checkpoint_events = []
        async def capture(event: Event):
            if "future" in event.payload:
                event.payload["future"].set_result(MagicMock(passed=True))
            checkpoint_events.append(event)

        await bus.subscribe("checkpoint_reached", capture)

        mock_llm.chat_with_tools = AsyncMock(side_effect=[
            make_tool_call_response("emit_checkpoint", {"name": "step1", "output": {"status": "ok"}}),
            make_text_response("Done!"),
        ])

        complete_events = []
        async def capture_complete(event: Event):
            complete_events.append(event)
        await bus.subscribe("task_complete", capture_complete)

        contract = make_contract()
        tenant = Tenant(
            contract=contract, llm_client=mock_llm, event_bus=bus,
            tools={}, work_dir=tmp_work_dir,
        )
        await tenant.run()

        assert len(checkpoint_events) == 1
        assert checkpoint_events[0].payload["name"] == "step1"
        assert len(complete_events) == 1

    async def test_shared_context_injected(self, bus, mock_llm, tmp_work_dir):
        mock_llm.chat_with_tools = AsyncMock(return_value=make_text_response("Done"))
        contract = make_contract()

        tenant = Tenant(
            contract=contract, llm_client=mock_llm, event_bus=bus,
            tools={}, work_dir=tmp_work_dir,
            shared_context="## db_engineer\n{\"tables\": [\"users\"]}",
        )
        await tenant.run()

        messages = mock_llm.chat_with_tools.call_args[0][0]
        system_content = " ".join(m.get("content", "") for m in messages if m["role"] == "system")
        assert "db_engineer" in system_content

    async def test_task_failed_on_error(self, bus, mock_llm, tmp_work_dir):
        mock_llm.chat_with_tools = AsyncMock(side_effect=Exception("LLM error"))

        events = []
        async def capture(event: Event):
            events.append(event)
        await bus.subscribe("task_failed", capture)

        contract = make_contract()
        tenant = Tenant(
            contract=contract, llm_client=mock_llm, event_bus=bus,
            tools={}, work_dir=tmp_work_dir,
        )
        await tenant.run()
        assert any(e.event_type == "task_failed" for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tenant.py -v
```

Expected: `ImportError: cannot import name 'Tenant' from 'landlord.tenant'` or `ModuleNotFoundError`

---

### Task 2: Implement landlord/tenant.py

**Files:**
- Create: `landlord/tenant.py`

- [ ] **Step 1: Write the implementation**

```python
"""Tenant worker - an isolated async agent that executes a contract."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from landlord.contract import Contract
from landlord.event_bus import Event, EventBus
from landlord.llm_client import LLMClient
from landlord.tools.base import Tool, ToolResult


EMIT_CHECKPOINT_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_checkpoint",
        "description": (
            "Declare that you have reached a checkpoint. "
            "The name must match one of the checkpoints in your contract."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Checkpoint name"},
                "output": {"type": "object", "description": "Checkpoint output data"},
            },
            "required": ["name", "output"],
        },
    },
}


class Tenant:
    """An isolated async worker that executes a contract."""

    def __init__(
        self,
        contract: Contract,
        llm_client: LLMClient,
        event_bus: EventBus,
        tools: dict[str, Tool],
        work_dir: Path,
        shared_context: str | None = None,
    ) -> None:
        self.contract = contract
        self._llm = llm_client
        self._bus = event_bus
        self._work_dir = work_dir
        self._shared_context = shared_context

        # Filter tools based on contract restrictions
        allowed_names = contract.effective_tools(list(tools.keys()))
        self._tools = {name: tools[name] for name in allowed_names if name in tools}

    def _build_system_message(self) -> str:
        parts = [
            f"You are a {self.contract.role}.",
            f"Objective: {self.contract.objective}",
        ]
        if self.contract.checkpoints:
            cp_desc = "\n".join(
                f"- {cp.name}: {cp.description}" for cp in self.contract.checkpoints
            )
            parts.append(f"Checkpoints to hit (call emit_checkpoint for each):\n{cp_desc}")
        if self._tools:
            tool_desc = "\n".join(f"- {name}" for name in self._tools)
            parts.append(f"Available tools:\n{tool_desc}")
        if self._shared_context:
            parts.append(f"Artifacts from dependencies:\n{self._shared_context}")
        return "\n\n".join(parts)

    def _build_tool_defs(self) -> list[dict]:
        defs = [EMIT_CHECKPOINT_TOOL]
        for tool in self._tools.values():
            defs.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return defs

    async def run(self) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_message()},
            {"role": "user", "content": self.contract.sub_prompt},
        ]
        if self.contract.context:
            messages.append({"role": "user", "content": f"Previous attempt context: {self.contract.context}"})

        tool_defs = self._build_tool_defs()

        try:
            while True:
                response = await self._llm.chat_with_tools(messages, tool_defs)
                choice = response.choices[0].message
                messages.append(choice.model_dump())

                if not choice.tool_calls:
                    await self._bus.publish(Event(
                        tenant_id=self.contract.tenant_id,
                        event_type="task_complete",
                        payload={"final_message": choice.content or ""},
                    ))
                    return

                for tool_call in choice.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    if fn_name == "emit_checkpoint":
                        future: asyncio.Future = asyncio.get_event_loop().create_future()
                        await self._bus.publish(Event(
                            tenant_id=self.contract.tenant_id,
                            event_type="checkpoint_reached",
                            payload={
                                "name": fn_args["name"],
                                "output": fn_args.get("output", {}),
                                "future": future,
                            },
                        ))
                        validation_result = await future
                        if not validation_result.passed:
                            return
                        tool_result_content = f"Checkpoint '{fn_args['name']}' validated successfully."
                    elif fn_name in self._tools:
                        result = await self._tools[fn_name].execute(**fn_args)
                        tool_result_content = result.output if result.success else f"Error: {result.error}"
                    else:
                        tool_result_content = f"Error: Unknown tool '{fn_name}'"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result_content,
                    })

        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._bus.publish(Event(
                tenant_id=self.contract.tenant_id,
                event_type="task_failed",
                payload={"error": str(e)},
            ))
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
pytest tests/test_tenant.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 3: Commit**

```bash
git add landlord/tenant.py tests/test_tenant.py
git commit -m "feat: add Tenant async worker with conversation loop and checkpoint emission"
```
