import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from landlord.legacy.llm_client import LLMClient


class TestLLMClient:
    @pytest.fixture
    def client(self):
        return LLMClient(model="test-model")

    async def test_chat(self, client):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello!"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("landlord.legacy.llm_client.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            result = await client.chat([{"role": "user", "content": "Hi"}])
            assert result == "Hello!"
            assert client.usage.prompt_tokens == 10
            assert client.usage.completion_tokens == 5
            assert client.usage.total == 15

    async def test_chat_with_tools(self, client):
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "file_write"
        tool_call.function.arguments = '{"path": "test.txt", "content": "hi"}'

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.tool_calls = [tool_call]
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10

        with patch("landlord.legacy.llm_client.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            result = await client.chat_with_tools(
                [{"role": "user", "content": "write a file"}],
                [{"type": "function", "function": {"name": "file_write"}}],
            )
            assert result.choices[0].message.tool_calls[0].function.name == "file_write"

    async def test_token_tracking_accumulates(self, client):
        def make_response(prompt_tokens, completion_tokens):
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "ok"
            resp.usage.prompt_tokens = prompt_tokens
            resp.usage.completion_tokens = completion_tokens
            return resp

        with patch("landlord.legacy.llm_client.litellm.acompletion", new_callable=AsyncMock) as mock:
            mock.side_effect = [make_response(10, 5), make_response(20, 10)]
            await client.chat([{"role": "user", "content": "1"}])
            await client.chat([{"role": "user", "content": "2"}])
            assert client.usage.prompt_tokens == 30
            assert client.usage.completion_tokens == 15

    async def test_independent_instances(self):
        c1 = LLMClient(model="m1")
        c2 = LLMClient(model="m2")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("landlord.legacy.llm_client.litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            await c1.chat([{"role": "user", "content": "hi"}])
            assert c1.usage.total == 15
            assert c2.usage.total == 0
