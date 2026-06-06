"""Runtime configuration for the SCOUTS-AI MCP client.

Values are read from environment variables so the same wheel can be reused
across local dev, CI and packaged MCP hosts (Claude Desktop, Cursor,
Open WebUI, etc.) without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration."""

    base_url: str
    timeout_s: float
    user_agent: str
    default_lang: str
    max_query_length: int
    max_page: int

    @staticmethod
    def from_env() -> "Config":
        return Config(
            base_url=_strip_trailing_slash(os.getenv("SCOUTS_AI_BASE_URL", "https://scouts-ai.com")),
            timeout_s=_float_env("SCOUTS_AI_TIMEOUT_S", 5.0, lo=0.1, hi=60.0),
            user_agent=os.getenv("SCOUTS_AI_USER_AGENT", "scouts-ai-mcp/0.1.1"),
            default_lang=os.getenv("SCOUTS_AI_DEFAULT_LANG", "en"),
            max_query_length=_int_env("SCOUTS_AI_MAX_QUERY_LENGTH", 512, lo=1, hi=4096),
            max_page=_int_env("SCOUTS_AI_MAX_PAGE", 10, lo=1, hi=100),
        )


def _strip_trailing_slash(url: str) -> str:
    return url[:-1] if url.endswith("/") else url


def _float_env(name: str, default: float, *, lo: float, hi: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"env {name} must be a float, got {raw!r}") from exc
    if not (lo <= value <= hi):
        raise ValueError(f"env {name} must be in [{lo}, {hi}], got {value}")
    return value


def _int_env(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"env {name} must be an int, got {raw!r}") from exc
    if not (lo <= value <= hi):
        raise ValueError(f"env {name} must be in [{lo}, {hi}], got {value}")
    return value
