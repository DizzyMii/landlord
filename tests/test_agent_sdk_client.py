"""Tests for the Agent-SDK-backed client."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from landlord.agent_sdk_client import AgentSDKClient


def _tool_def() -> dict[str, Any]:
    return {
        "name": "judge_checkpoint",
        "description": "Record verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["passed", "reason"],
        },
    }


@pytest.mark.asyncio
async def test_call_forced_tool_raises_when_tool_not_called():
    captured_options: list = []

    async def empty_query(prompt, options):
        captured_options.append((prompt, options))
        if False:
            yield  # make it an async generator

    client = AgentSDKClient(model="claude-sonnet-4-6", query_fn=empty_query)
    with pytest.raises(RuntimeError, match="did not call forced tool"):
        await client.call_forced_tool(
            system="You judge things.",
            messages=[{"role": "user", "content": "judge this"}],
            tool=_tool_def(),
        )

    assert len(captured_options) == 1
    prompt, options = captured_options[0]
    assert prompt == "judge this"
    assert options.model == "claude-sonnet-4-6"
    assert options.allowed_tools == ["mcp__forced_tool__judge_checkpoint"]
    assert "mcp__forced_tool__judge_checkpoint" not in options.system_prompt
    assert "judge_checkpoint" in options.system_prompt
    assert "You MUST call" in options.system_prompt
    assert "You judge things." in options.system_prompt
    assert "forced_tool" in options.mcp_servers
    assert options.setting_sources is None
    assert options.skills is None


@pytest.mark.asyncio
async def test_call_forced_tool_concatenates_multiple_user_messages():
    captured = []

    async def q(prompt, options):
        captured.append(prompt)
        if False:
            yield

    client = AgentSDKClient(model="m", query_fn=q)
    with pytest.raises(RuntimeError):
        await client.call_forced_tool(
            system="s",
            messages=[
                {"role": "user", "content": "first"},
                {"role": "user", "content": "second"},
            ],
            tool=_tool_def(),
        )
    assert captured == ["first\n\nsecond"]
