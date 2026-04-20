"""Web search tool for tenant workers."""
from __future__ import annotations

import os

import httpx

from landlord.legacy.tools.base import ToolResult


class WebSearchTool:
    """Searches the web via a configured search API."""

    name = "web_search"
    description = "Search the web using a search API."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query string"},
        },
        "required": ["query"],
    }

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._api_url = api_url or os.environ.get("SEARCH_API_URL")
        self._api_key = api_key or os.environ.get("SEARCH_API_KEY")

    async def execute(self, **kwargs) -> ToolResult:
        query: str = kwargs["query"]
        if not self._api_url:
            return ToolResult(
                success=False,
                output="",
                error="No search API configured. Set SEARCH_API_URL or pass api_url.",
            )
        payload: dict = {"query": query}
        if self._api_key:
            payload["api_key"] = self._api_key
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self._api_url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

        results = data.get("results", [])
        lines = [f"{r.get('title', 'No title')}: {r.get('url', '')}" for r in results]
        return ToolResult(success=True, output="\n".join(lines))
