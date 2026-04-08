import pytest
from landlord.tools.base import Tool, ToolResult


class TestToolResult:
    def test_success_result(self):
        result = ToolResult(success=True, output="file written")
        assert result.success is True
        assert result.output == "file written"
        assert result.error is None

    def test_error_result(self):
        result = ToolResult(success=False, output="", error="Access denied")
        assert result.success is False
        assert result.error == "Access denied"


class TestToolProtocol:
    async def test_concrete_tool_satisfies_protocol(self):
        class MockTool:
            name = "mock"
            description = "A mock tool"
            parameters = {"type": "object", "properties": {"msg": {"type": "string"}}}

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, output=kwargs.get("msg", ""))

        tool: Tool = MockTool()
        result = await tool.execute(msg="hello")
        assert result.success is True
        assert result.output == "hello"
