"""Tests for the thin Anthropic SDK wrapper."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from landlord.anthropic_client import AnthropicClient, CachedBlock


@pytest.mark.asyncio
async def test_messages_applies_cache_control_to_system_blocks(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="hello")]
    fake_response.stop_reason = "end_turn"
    fake_response.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    system_blocks = [
        CachedBlock(text="You are a helpful assistant.", cache=True),
        CachedBlock(text="Additional context that is not cached.", cache=False),
    ]
    await client.messages(system=system_blocks, messages=[{"role": "user", "content": "hi"}])

    sent_system = fake_sdk.messages.create.call_args.kwargs["system"]
    assert sent_system == [
        {"type": "text", "text": "You are a helpful assistant.", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Additional context that is not cached."},
    ]


@pytest.mark.asyncio
async def test_call_forced_tool_returns_parsed_arguments(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "judge_checkpoint"
    tool_block.input = {"passed": True, "reason": "looks good"}
    fake_response.content = [tool_block]
    fake_response.stop_reason = "tool_use"
    fake_response.usage = MagicMock(
        input_tokens=10, output_tokens=5,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    tool = {
        "name": "judge_checkpoint",
        "description": "Judge whether the output meets the criterion.",
        "input_schema": {
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["passed", "reason"],
        },
    }
    result = await client.call_forced_tool(
        system=[CachedBlock(text="You are a judge.", cache=True)],
        messages=[{"role": "user", "content": "judge this"}],
        tool=tool,
    )
    assert result == {"passed": True, "reason": "looks good"}
    call = fake_sdk.messages.create.call_args.kwargs
    assert call["tool_choice"] == {"type": "tool", "name": "judge_checkpoint"}
    assert call["tools"] == [tool]


@pytest.mark.asyncio
async def test_call_forced_tool_raises_when_tool_not_called(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    text_block = MagicMock(type="text", text="I refuse")
    fake_response.content = [text_block]
    fake_response.stop_reason = "end_turn"
    fake_response.usage = MagicMock(
        input_tokens=5, output_tokens=3,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    tool = {
        "name": "judge_checkpoint",
        "description": "Judge.",
        "input_schema": {"type": "object", "properties": {"passed": {"type": "boolean"}}, "required": ["passed"]},
    }
    with pytest.raises(
        RuntimeError,
        match=r"did not call forced tool 'judge_checkpoint'.*stop_reason=.*content_types=",
    ):
        await client.call_forced_tool(
            system=[CachedBlock(text="Judge.", cache=True)],
            messages=[{"role": "user", "content": "x"}],
            tool=tool,
        )


@pytest.mark.asyncio
async def test_usage_stats_accumulate(mocker):
    fake_sdk = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text="ok")]
    fake_response.stop_reason = "end_turn"
    fake_response.usage = MagicMock(
        input_tokens=100, output_tokens=50,
        cache_creation_input_tokens=200, cache_read_input_tokens=300,
    )
    fake_sdk.messages.create = AsyncMock(return_value=fake_response)
    mocker.patch("landlord.anthropic_client.AsyncAnthropic", return_value=fake_sdk)

    client = AnthropicClient(model="claude-opus-4-7")
    await client.messages(system=[CachedBlock(text="s", cache=True)], messages=[{"role": "user", "content": "hi"}])
    await client.messages(system=[CachedBlock(text="s", cache=True)], messages=[{"role": "user", "content": "hi"}])
    assert client.usage.input_tokens == 200
    assert client.usage.output_tokens == 100
    assert client.usage.cache_creation_input_tokens == 400
    assert client.usage.cache_read_input_tokens == 600
