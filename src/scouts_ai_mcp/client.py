"""Synchronous HTTP client for the SCOUTS-AI `/api/search` endpoint.

Design notes:
- Synchronous on purpose. fastmcp v2 tool functions are called from the MCP
  event loop; the underlying httpx call is fast (one short JSON GET) and
  keeping the client sync avoids the cost and complexity of async/await
  plumbing for a single tool.
- All errors are mapped to typed exceptions from :mod:`scouts_ai_mcp.errors`
  so the MCP tool layer can render friendly messages to the model.
- The client owns its ``httpx.Client`` lifecycle. Callers should use the
  :class:`ScoutsAiClient` as a context manager so the HTTP pool is released.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config
from .errors import (
    ApiError,
    InvalidQueryError,
    RateLimitedError,
    UpstreamUnavailableError,
)

# BCP-47-like: letters, digits, dashes. Mirrors the backend validator.
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


@dataclass(frozen=True)
class SearchResult:
    """A single SCOUTS-AI search hit."""

    title: str
    url: str
    content: str
    published_at: str | None
    engine: str | None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SearchResult":
        return cls(
            title=str(raw.get("title", "")),
            url=str(raw.get("url", "")),
            content=str(raw.get("content", "")),
            published_at=_as_optional_str(raw.get("publishedAt")),
            engine=_as_optional_str(raw.get("engine")),
        )


@dataclass(frozen=True)
class SearchResponse:
    """Full SCOUTS-AI response payload (mirrors backend fields)."""

    query: str
    lang: str
    page: int
    page_size: int
    cached: bool
    took_ms: int
    results: tuple[SearchResult, ...]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SearchResponse":
        results_raw = raw.get("results") or []
        if not isinstance(results_raw, list):
            raise ApiError("Upstream returned non-list results", code="BAD_PAYLOAD", status=200)
        return cls(
            query=str(raw.get("query", "")),
            lang=str(raw.get("lang", "")),
            page=int(raw.get("page", 1)),
            page_size=int(raw.get("pageSize", len(results_raw))),
            cached=bool(raw.get("cached", False)),
            took_ms=int(raw.get("tookMs", 0)),
            results=tuple(SearchResult.from_json(r) for r in results_raw if isinstance(r, dict)),
        )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


class ScoutsAiClient:
    """Thin typed wrapper around ``GET /api/search``."""

    def __init__(self, config: Config | None = None, *, http_client: httpx.Client | None = None) -> None:
        self._config = config or Config.from_env()
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(self._config.timeout_s),
            headers={"User-Agent": self._config.user_agent, "Accept": "application/json"},
        )

    def __enter__(self) -> "ScoutsAiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    @property
    def config(self) -> Config:
        return self._config

    # ------------------------------------------------------------------ search

    def search(self, query: str, *, lang: str | None = None, page: int = 1) -> SearchResponse:
        """Call ``GET /api/search`` and return a typed response."""
        q = self._validate_query(query)
        effective_lang = self._validate_lang(lang or self._config.default_lang)
        effective_page = self._validate_page(page)

        try:
            response = self._http.get(
                "/api/search",
                params={"q": q, "lang": effective_lang, "page": str(effective_page)},
            )
        except httpx.TimeoutException as exc:
            raise UpstreamUnavailableError(
                f"SCOUTS-AI request timed out after {self._config.timeout_s}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(f"SCOUTS-AI network error: {exc}") from exc

        return self._parse(response)

    # ----------------------------------------------------------------- helpers

    def _validate_query(self, query: str) -> str:
        if not isinstance(query, str):
            raise InvalidQueryError("query must be a string")
        q = query.strip()
        if not q:
            raise InvalidQueryError("query must not be empty")
        if len(q) > self._config.max_query_length:
            raise InvalidQueryError(
                f"query too long: {len(q)} > {self._config.max_query_length} chars"
            )
        return q

    def _validate_lang(self, lang: str) -> str:
        if not _LANG_RE.match(lang):
            raise InvalidQueryError(f"invalid lang: {lang!r} (expected BCP-47, e.g. 'en', 'en-US')")
        return lang

    def _validate_page(self, page: int) -> int:
        if not isinstance(page, int) or isinstance(page, bool):
            raise InvalidQueryError("page must be an int")
        if page < 1 or page > self._config.max_page:
            raise InvalidQueryError(f"page out of range: {page} (1..{self._config.max_page})")
        return page

    def _parse(self, response: httpx.Response) -> SearchResponse:
        if response.status_code == 429:
            retry = _parse_retry_after(response.headers.get("Retry-After"))
            msg = "Rate limit exceeded"
            if retry is not None:
                msg = f"{msg}; retry after {retry:g}s"
            raise RateLimitedError(msg, retry_after_s=retry)

        if response.status_code >= 500:
            raise UpstreamUnavailableError(
                f"SCOUTS-AI upstream error {response.status_code}: {response.text[:200]}"
            )

        if response.status_code >= 400:
            payload = _safe_json(response)
            code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
            message = (
                payload.get("error", {}).get("message")
                if isinstance(payload, dict)
                else None
            ) or response.text[:200] or f"HTTP {response.status_code}"
            raise ApiError(str(message), code=code, status=response.status_code)

        payload = _safe_json(response)
        if not isinstance(payload, dict):
            raise UpstreamUnavailableError("SCOUTS-AI returned non-object JSON")
        return SearchResponse.from_json(payload)


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
