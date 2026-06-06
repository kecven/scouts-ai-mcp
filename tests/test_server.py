"""Smoke + behavior tests for the fastmcp server tool."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import Client

from scouts_ai_mcp.config import Config
from scouts_ai_mcp.server import build_server


PAYLOAD = {
    "query": "rust async",
    "lang": "en",
    "page": 1,
    "pageSize": 1,
    "cached": False,
    "tookMs": 5,
    "results": [
        {
            "title": "Tokio",
            "url": "https://tokio.rs/",
            "content": "Async runtime.",
            "publishedAt": None,
            "engine": "duckduckgo",
        }
    ],
}


def _client_with_mocked_upstream() -> tuple[Client, respx.Router]:
    cfg = Config(
        base_url="https://scouts-ai.test",
        timeout_s=2.0,
        user_agent="scouts-ai-mcp-tests",
        default_lang="en",
        max_query_length=512,
        max_page=10,
    )
    http = httpx.Client(
        base_url=cfg.base_url,
        headers={"User-Agent": cfg.user_agent, "Accept": "application/json"},
    )
    from scouts_ai_mcp.client import ScoutsAiClient
    server = build_server(client=ScoutsAiClient(config=cfg, http_client=http))
    mock = respx.mock(base_url=cfg.base_url)
    return Client(server), mock


@pytest.mark.asyncio
async def test_web_search_tool_returns_payload() -> None:
    client, mock = _client_with_mocked_upstream()
    with mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        async with client:
            result = await client.call_tool(
                "web_search",
                {"query": "Rust Async", "lang": "en", "page": 1},
            )

    assert result.structured_content is not None
    data = result.structured_content
    assert data["query"] == "rust async"
    assert data["results"][0]["url"] == "https://tokio.rs/"
    qs = str(route.calls.last.request.url)
    # Client only trims; case is preserved on the wire (server normalizes).
    assert "q=Rust+Async" in qs
    assert "lang=en" in qs
    assert "page=1" in qs


@pytest.mark.asyncio
async def test_web_search_tool_uses_default_lang_and_page() -> None:
    client, mock = _client_with_mocked_upstream()
    with mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        async with client:
            await client.call_tool("web_search", {"query": "hello"})

    qs = str(route.calls.last.request.url)
    assert "lang=en" in qs
    assert "page=1" in qs


@pytest.mark.asyncio
async def test_web_search_tool_reports_invalid_args() -> None:
    client, mock = _client_with_mocked_upstream()
    with mock:
        async with client:
            with pytest.raises(Exception) as excinfo:
                await client.call_tool("web_search", {"query": ""})
    assert "Invalid search arguments" in str(excinfo.value) or "query" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_web_search_tool_reports_rate_limit() -> None:
    client, mock = _client_with_mocked_upstream()
    with mock:
        mock.get("/api/search").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "3"})
        )
        async with client:
            with pytest.raises(Exception) as excinfo:
                await client.call_tool("web_search", {"query": "ok"})
    msg = str(excinfo.value)
    assert "rate limit" in msg.lower()
    assert "3" in msg


@pytest.mark.asyncio
async def test_web_search_tool_reports_upstream_unavailable() -> None:
    client, mock = _client_with_mocked_upstream()
    with mock:
        mock.get("/api/search").mock(return_value=httpx.Response(503, text="boom"))
        async with client:
            with pytest.raises(Exception) as excinfo:
                await client.call_tool("web_search", {"query": "ok"})
    assert "temporarily unavailable" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_server_lists_web_search_tool() -> None:
    cfg = Config(
        base_url="https://scouts-ai.test",
        timeout_s=2.0,
        user_agent="scouts-ai-mcp-tests",
        default_lang="en",
        max_query_length=512,
        max_page=10,
    )
    server = build_server()
    # The injected client only matters for tool calls; listing tools does not
    # touch the network.
    _ = cfg
    async with Client(server) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert "web_search" in names
    tool = next(t for t in tools if t.name == "web_search")
    # Schema sanity: query, lang, page are exposed.
    props = tool.inputSchema.get("properties", {})
    assert {"query", "lang", "page"} <= set(props)
