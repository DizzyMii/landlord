"""Web fetch tool for tenant workers."""
from __future__ import annotations

import httpx

from landlord.tools.base import ToolResult


class WebFetchTool:
    """Fetches content from a URL via HTTP GET."""

    name = "web_fetch"
    description = "Fetch the content of a URL via HTTP GET."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
        },
        "required": ["url"],
    }

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    async def execute(self, **kwargs) -> ToolResult:
        url: str = kwargs["url"]
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                return ToolResult(success=True, output=response.text)
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))
