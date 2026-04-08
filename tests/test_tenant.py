import json
import pytest
from unittest.mock import AsyncMock, MagicMock

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
            make_tool_call_response("emit_checkpoint__step1", {"status": "ok"}),
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
