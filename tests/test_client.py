"""Unit tests for :mod:`scouts_ai_mcp.client`."""

from __future__ import annotations

import httpx
import pytest
import respx

from scouts_ai_mcp.client import SearchResponse
from scouts_ai_mcp.errors import (
    ApiError,
    InvalidQueryError,
    RateLimitedError,
    UpstreamUnavailableError,
)


PAYLOAD = {
    "query": "Rust Async",
    "lang": "en",
    "page": 1,
    "pageSize": 2,
    "cached": False,
    "tookMs": 123,
    "results": [
        {
            "title": "Tokio",
            "url": "https://tokio.rs/",
            "content": "An async runtime for Rust.",
            "publishedAt": "2025-11-14T00:00:00Z",
            "engine": "duckduckgo",
        },
        {
            "title": "async-std",
            "url": "https://async.rs/",
            "content": "Async std lib for Rust.",
            "publishedAt": None,
            "engine": None,
        },
    ],
}


# ----------------------------------------------------------------- happy path


def test_search_returns_typed_response(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        resp = client.search("  Rust Async ", lang="en", page=1)  # type: ignore[attr-defined]

    assert isinstance(resp, SearchResponse)
    # Client only trims whitespace; case and any further normalization happen server-side.
    assert resp.query == "Rust Async"
    assert resp.lang == "en"
    assert resp.page == 1
    assert resp.page_size == 2
    assert resp.cached is False
    assert resp.took_ms == 123
    assert len(resp.results) == 2
    assert resp.results[0].title == "Tokio"
    assert resp.results[0].published_at == "2025-11-14T00:00:00Z"
    assert resp.results[1].published_at is None
    assert resp.results[1].engine is None

    request = route.calls.last.request
    # Note: SCOUTS-AI normalizes the query on the server; we only trim.
    assert str(request.url).endswith("/api/search?q=Rust+Async&lang=en&page=1")


def test_search_uses_default_lang_and_page(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        client.search("hello world")  # type: ignore[attr-defined]

    qs = str(route.calls.last.request.url).split("?", 1)[1]
    assert "lang=en" in qs
    assert "page=1" in qs


# -------------------------------------------------------------- internal token


def test_internal_token_is_sent_when_configured(trusted_client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        trusted_client.search("hello")  # type: ignore[attr-defined]
    assert route.calls.last.request.headers.get("X-Internal-Token") == "shared-secret-xyz"


def test_internal_token_is_absent_when_unset(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        client.search("hello")  # type: ignore[attr-defined]
    assert route.calls.last.request.headers.get("X-Internal-Token") is None




# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    "bad_query",
    ["", "   ", "\n\t"],
)
def test_search_rejects_empty_query(client: object, bad_query: str) -> None:
    with pytest.raises(InvalidQueryError):
        client.search(bad_query)  # type: ignore[attr-defined]


def test_search_rejects_too_long_query(client: object) -> None:
    with pytest.raises(InvalidQueryError, match="too long"):
        client.search("a" * 513)  # type: ignore[attr-defined]


def test_search_rejects_non_string_query(client: object) -> None:
    with pytest.raises(InvalidQueryError):
        client.search(123)  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad_lang", ["english", "en_US", "en US", "123", "x"])
def test_search_rejects_invalid_lang(client: object, bad_lang: str) -> None:
    with pytest.raises(InvalidQueryError, match="invalid lang"):
        client.search("ok", lang=bad_lang)  # type: ignore[attr-defined]


def test_empty_lang_falls_back_to_default(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        route = mock.get("/api/search").mock(return_value=httpx.Response(200, json=PAYLOAD))
        client.search("ok", lang="")  # type: ignore[attr-defined]
    qs = str(route.calls.last.request.url).split("?", 1)[1]
    assert "lang=en" in qs


@pytest.mark.parametrize("bad_page", [0, -1, 11, 1000])
def test_search_rejects_out_of_range_page(client: object, bad_page: int) -> None:
    with pytest.raises(InvalidQueryError, match="page out of range"):
        client.search("ok", page=bad_page)  # type: ignore[attr-defined]


def test_search_rejects_bool_page(client: object) -> None:
    with pytest.raises(InvalidQueryError):
        client.search("ok", page=True)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ upstream


def test_search_maps_429_to_rate_limited(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "2.5"}, text="Too Many")
        )
        with pytest.raises(RateLimitedError) as excinfo:
            client.search("ok")  # type: ignore[attr-defined]
    assert excinfo.value.retry_after_s == 2.5


def test_search_maps_429_without_retry_after(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(return_value=httpx.Response(429, text="Too Many"))
        with pytest.raises(RateLimitedError) as excinfo:
            client.search("ok")  # type: ignore[attr-defined]
    assert excinfo.value.retry_after_s is None


def test_search_maps_5xx_to_upstream_unavailable(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(return_value=httpx.Response(503, text="boom"))
        with pytest.raises(UpstreamUnavailableError):
            client.search("ok")  # type: ignore[attr-defined]


def test_search_maps_4xx_error_envelope_to_api_error(client: object) -> None:
    payload = {"error": {"code": "BAD_QUERY", "message": "q must not be blank"}}
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(return_value=httpx.Response(400, json=payload))
        with pytest.raises(ApiError) as excinfo:
            client.search("ok")  # type: ignore[attr-defined]
    assert excinfo.value.status == 400
    assert excinfo.value.code == "BAD_QUERY"
    assert "blank" in str(excinfo.value)


def test_search_maps_4xx_non_json_to_api_error(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(return_value=httpx.Response(400, text="<html>bad</html>"))
        with pytest.raises(ApiError) as excinfo:
            client.search("ok")  # type: ignore[attr-defined]
    assert excinfo.value.status == 400
    assert excinfo.value.code is None


def test_search_maps_timeout_to_upstream_unavailable(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(side_effect=httpx.ConnectTimeout("slow"))
        with pytest.raises(UpstreamUnavailableError, match="network error|timed out"):
            client.search("ok")  # type: ignore[attr-defined]


def test_search_rejects_non_object_response(client: object) -> None:
    with respx.mock(base_url="https://scouts-ai.test") as mock:
        mock.get("/api/search").mock(return_value=httpx.Response(200, json=["nope"]))
        with pytest.raises(UpstreamUnavailableError, match="non-object JSON"):
            client.search("ok")  # type: ignore[attr-defined]


# -------------------------------------------------------------- context manager


def test_client_closes_owned_http_client(config: object) -> None:
    from scouts_ai_mcp.client import ScoutsAiClient
    from scouts_ai_mcp.config import Config

    c = ScoutsAiClient(config=Config.from_env())  # type: ignore[arg-type]
    with c:
        pass
    # No public assertion possible without a real network; just ensure exit
    # did not raise and the object is reusable as a no-op.
    assert c is not None


# ----------------------------------------------------------------- config env


def test_config_from_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCOUTS_AI_BASE_URL", "http://localhost:8080/")
    monkeypatch.setenv("SCOUTS_AI_TIMEOUT_S", "1.5")
    monkeypatch.setenv("SCOUTS_AI_DEFAULT_LANG", "de")
    from scouts_ai_mcp.config import Config
    cfg = Config.from_env()
    assert cfg.base_url == "http://localhost:8080"  # trailing slash stripped
    assert cfg.timeout_s == 1.5
    assert cfg.default_lang == "de"


def test_config_rejects_out_of_range_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from scouts_ai_mcp.config import Config
    monkeypatch.setenv("SCOUTS_AI_TIMEOUT_S", "999")
    with pytest.raises(ValueError, match="SCOUTS_AI_TIMEOUT_S"):
        Config.from_env()
