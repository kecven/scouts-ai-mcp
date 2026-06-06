"""MCP server exposing SCOUTS-AI as a single ``web_search`` tool.

Usage:
    # stdio (default; what Claude Desktop / Cursor / Open WebUI expect):
    scouts-ai-mcp

    # HTTP transport (for remote MCP hosts):
    scouts-ai-mcp --transport http --host 127.0.0.1 --port 8765

    # Custom base URL:
    SCOUTS_AI_BASE_URL=http://localhost:8080 scouts-ai-mcp

The server keeps a single :class:`ScoutsAiClient` for its lifetime. MCP tools
are called one at a time per request, so no internal locking is required.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from . import __version__
from .client import ScoutsAiClient
from .config import Config
from .errors import (
    ApiError,
    InvalidQueryError,
    RateLimitedError,
    UpstreamUnavailableError,
)

logger = logging.getLogger("scouts_ai_mcp")

INSTRUCTIONS = (
    "SCOUTS-AI web search MCP server. Use the `web_search` tool to get fresh, "
    "compact JSON search results from the public SCOUTS-AI API "
    "(GET https://scouts-ai.com/api/search). No API key is required. "
    "Prefer results with a populated `publishedAt` field when the user asks "
    "about recent events, and use `url` values as citation candidates. "
    "Respect rate limits: on 429, back off for the suggested `Retry-After` "
    "seconds before retrying. Do not crawl or bulk-index the API."
)


def build_server(client: ScoutsAiClient | None = None) -> FastMCP:
    """Construct a FastMCP server instance.

    A custom client can be injected for tests; otherwise a default one is
    created on first use.
    """
    server = FastMCP(
        name="scouts-ai",
        instructions=INSTRUCTIONS,
        version=__version__,
    )

    @server.tool(
        name="web_search",
        description=(
            "Search the public web via SCOUTS-AI and return compact JSON results. "
            "Use this when the user asks a question that requires current information, "
            "fresh context, or citations from the open web. No API key required. "
            "Returns at most 10 results per page."
        ),
    )
    def web_search(
        query: str,
        lang: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        """Perform a SCOUTS-AI web search.

        Args:
            query: Natural-language search query, 1-512 characters.
            lang: Optional BCP-47 language code (e.g. "en", "en-US"). Defaults to "en".
            page: Optional 1-based page number, 1-10. Defaults to 1.

        Returns:
            A dict matching the SCOUTS-AI ``/api/search`` response shape.

        Raises:
            ToolError: If the upstream returns a non-2xx response or the request fails.
        """
        c = client or _get_default_client()
        try:
            response = c.search(query, lang=lang, page=page)
        except InvalidQueryError as exc:
            raise ToolError(f"Invalid search arguments: {exc}") from exc
        except RateLimitedError as exc:
            hint = f" (retry after {exc.retry_after_s:g}s)" if exc.retry_after_s else ""
            raise ToolError(
                "SCOUTS-AI rate limit exceeded" + hint
                + ". Reduce request rate and try again later."
            ) from exc
        except UpstreamUnavailableError as exc:
            raise ToolError(
                "SCOUTS-AI is temporarily unavailable. Tell the user the web search "
                "service is down and suggest retrying later."
            ) from exc
        except ApiError as exc:
            raise ToolError(f"SCOUTS-AI rejected the request ({exc.code or exc.status}): {exc}") from exc

        return {
            "query": response.query,
            "lang": response.lang,
            "page": response.page,
            "pageSize": response.page_size,
            "cached": response.cached,
            "tookMs": response.took_ms,
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "content": r.content,
                    "publishedAt": r.published_at,
                    "engine": r.engine,
                }
                for r in response.results
            ],
        }

    return server


# ----------------------------------------------------------------- default client


_default_client_instance: ScoutsAiClient | None = None


def _get_default_client() -> ScoutsAiClient:
    global _default_client_instance
    if _default_client_instance is None:
        _default_client_instance = ScoutsAiClient()
    return _default_client_instance


def _reset_default_client_for_tests() -> None:
    """Test hook: drop the cached default client so a fresh one is built next call."""
    global _default_client_instance
    _default_client_instance = None


# ----------------------------------------------------------------- CLI entrypoint


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scouts-ai-mcp",
        description="MCP server for the SCOUTS-AI web search API.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http", "sse"),
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP/SSE bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="HTTP/SSE bind port (default: 8765).")
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Logging level (default: WARNING).",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print effective runtime config as JSON and exit.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.version:
        print(__version__)
        return
    if args.print_config:
        cfg = Config.from_env()
        print(json.dumps(cfg.__dict__, indent=2))
        return

    server = build_server()
    logger.info("starting scouts-ai-mcp %s (transport=%s)", __version__, args.transport)
    if args.transport == "stdio":
        server.run(transport="stdio")
    elif args.transport == "http":
        server.run(transport="http", host=args.host, port=args.port)
    else:  # sse
        server.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
