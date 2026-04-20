import os
from unittest.mock import AsyncMock, patch

from landlord.legacy.tools.base import Tool, ToolResult
from landlord.legacy.tools.file_write import FileWriteTool
from landlord.legacy.tools.file_read import FileReadTool
from landlord.legacy.tools.shell_exec import ShellExecTool
from landlord.legacy.tools.web_fetch import WebFetchTool
from landlord.legacy.tools.web_search import WebSearchTool


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



class TestFileWriteTool:
    async def test_write_file(self, tmp_work_dir):
        tool = FileWriteTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="test.txt", content="hello world")
        assert result.success is True
        assert (tmp_work_dir / "test.txt").read_text() == "hello world"

    async def test_write_creates_subdirectories(self, tmp_work_dir):
        tool = FileWriteTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="sub/dir/test.txt", content="nested")
        assert result.success is True
        assert (tmp_work_dir / "sub" / "dir" / "test.txt").read_text() == "nested"

    async def test_write_rejects_path_traversal(self, tmp_work_dir):
        tool = FileWriteTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="../../../etc/passwd", content="hacked")
        assert result.success is False
        assert "denied" in result.error.lower()


class TestFileReadTool:
    async def test_read_file(self, tmp_work_dir):
        (tmp_work_dir / "test.txt").write_text("hello")
        tool = FileReadTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="test.txt")
        assert result.success is True
        assert result.output == "hello"

    async def test_read_missing_file(self, tmp_work_dir):
        tool = FileReadTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="nonexistent.txt")
        assert result.success is False

    async def test_read_rejects_path_traversal(self, tmp_work_dir):
        tool = FileReadTool(base_dir=tmp_work_dir)
        result = await tool.execute(path="../../etc/passwd")
        assert result.success is False
        assert "denied" in result.error.lower()


class TestShellExecTool:
    async def test_run_command(self, tmp_work_dir):
        tool = ShellExecTool(base_dir=tmp_work_dir)
        result = await tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.output

    async def test_command_failure(self, tmp_work_dir):
        tool = ShellExecTool(base_dir=tmp_work_dir)
        result = await tool.execute(command="exit 1")
        assert result.success is False

    async def test_timeout(self, tmp_work_dir):
        tool = ShellExecTool(base_dir=tmp_work_dir, timeout=1)
        result = await tool.execute(command="sleep 10")
        assert result.success is False
        assert "timeout" in result.error.lower()


class TestWebFetchTool:
    async def test_fetch_url(self):
        tool = WebFetchTool()
        mock_response = AsyncMock()
        mock_response.text = "page content"
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        with patch("landlord.legacy.tools.web_fetch.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            result = await tool.execute(url="https://example.com")
            assert result.success is True
            assert result.output == "page content"


class TestWebSearchTool:
    async def test_search(self):
        tool = WebSearchTool(api_url="https://search.example.com")
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"results": [{"title": "Result 1", "url": "https://example.com"}]}
        mock_response.raise_for_status = lambda: None

        with patch("landlord.legacy.tools.web_search.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            result = await tool.execute(query="python async")
            assert result.success is True
            assert "Result 1" in result.output

    async def test_search_no_api_url(self):
        tool = WebSearchTool(api_url=None, api_key=None)
        os.environ.pop("SEARCH_API_URL", None)
        result = await tool.execute(query="something")
        assert result.success is False
        assert "api" in result.error.lower() or "configured" in result.error.lower()
