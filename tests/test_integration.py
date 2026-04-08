import json
from unittest.mock import AsyncMock, MagicMock, patch

from landlord.config import LandlordConfig
from landlord.event_bus import EventBus
from landlord.landlord import Landlord
from landlord.llm_client import LLMClient
from landlord.renderer import Renderer
from landlord.validator import Validator, ValidationResult


def make_decompose_response():
    return json.dumps([{
        "role": "writer",
        "objective": "Write a greeting",
        "sub_prompt": "Write a friendly greeting message and save it to greeting.txt",
        "checkpoints": [{
            "name": "greeting_written",
            "description": "A greeting file exists",
            "schema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]},
        }],
        "output_schema": {"type": "object"},
    }])


def make_tenant_text_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.choices[0].message.model_dump.return_value = {"role": "assistant", "content": content, "tool_calls": None}
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


def make_tenant_tool_response(name, args, call_id="call_1"):
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(args)

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = None
    resp.choices[0].message.tool_calls = [tool_call]
    resp.choices[0].message.model_dump.return_value = {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
    }
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


class TestFullFlow:
    async def test_simple_prompt_to_completion(self, tmp_path):
        config = LandlordConfig(auto_approve=True, output_dir=str(tmp_path / "output"))

        landlord_llm = MagicMock(spec=LLMClient)
        landlord_llm.model = "test-model"
        landlord_llm.chat = AsyncMock(return_value=make_decompose_response())

        tenant_responses = [
            make_tenant_tool_response("file_write", {"path": "greeting.txt", "content": "Hello!"}),
            make_tenant_tool_response("emit_checkpoint", {"name": "greeting_written", "output": {"file": "greeting.txt"}}),
            make_tenant_text_response("Done! I wrote the greeting."),
        ]

        bus = EventBus()
        validator = MagicMock(spec=Validator)
        validator.validate_checkpoint = AsyncMock(
            return_value=ValidationResult(passed=True, tier=1, explanation="OK")
        )
        renderer = MagicMock(spec=Renderer)

        landlord = Landlord(
            config=config, llm_client=landlord_llm, event_bus=bus,
            validator=validator, renderer=renderer,
        )

        with patch("landlord.landlord.LLMClient") as mock_llm_cls:
            tenant_llm = MagicMock(spec=LLMClient)
            tenant_llm.chat_with_tools = AsyncMock(side_effect=tenant_responses)
            mock_llm_cls.return_value = tenant_llm

            await landlord.run("Write a greeting")

        renderer.show_plan.assert_called_once()
        renderer.tenant_started.assert_called_once()
        renderer.tenant_completed.assert_called_once()
        assert (tmp_path / "output").exists()

    async def test_eviction_and_retry(self, tmp_path):
        config = LandlordConfig(auto_approve=True, output_dir=str(tmp_path / "output"), max_retries=2)

        landlord_llm = MagicMock(spec=LLMClient)
        landlord_llm.model = "test-model"
        landlord_llm.chat = AsyncMock(return_value=json.dumps([{
            "role": "worker",
            "objective": "Do task",
            "sub_prompt": "Do the task",
            "checkpoints": [
                {"name": "done", "description": "Task complete", "schema": {"type": "object", "required": ["result"]}},
            ],
            "output_schema": {"type": "object"},
            "max_retries": 2,
        }]))

        bus = EventBus()
        call_count = 0

        async def validate_side_effect(output, checkpoint, contract):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ValidationResult(passed=False, tier=1, explanation="Missing field", errors=["'result' required"])
            return ValidationResult(passed=True, tier=1, explanation="OK")

        validator = MagicMock(spec=Validator)
        validator.validate_checkpoint = AsyncMock(side_effect=validate_side_effect)
        renderer = MagicMock(spec=Renderer)

        landlord = Landlord(
            config=config, llm_client=landlord_llm, event_bus=bus,
            validator=validator, renderer=renderer,
        )

        attempt = [0]

        def make_tenant_mock(model):
            attempt[0] += 1
            mock = MagicMock(spec=LLMClient)
            if attempt[0] == 1:
                mock.chat_with_tools = AsyncMock(side_effect=[
                    make_tenant_tool_response("emit_checkpoint", {"name": "done", "output": {"bad": "data"}}),
                    make_tenant_text_response("Done"),
                ])
            else:
                mock.chat_with_tools = AsyncMock(side_effect=[
                    make_tenant_tool_response("emit_checkpoint", {"name": "done", "output": {"result": "success"}}),
                    make_tenant_text_response("Done properly this time"),
                ])
            return mock

        with patch("landlord.landlord.LLMClient", side_effect=make_tenant_mock):
            await landlord.run("Do a task")

        assert renderer.tenant_evicted.called or renderer.checkpoint_failed.called
