"""Typed exceptions raised by the SCOUTS-AI client and surfaced to MCP tools."""

from __future__ import annotations


class ScoutsAiError(Exception):
    """Base error for all SCOUTS-AI client failures."""


class InvalidQueryError(ScoutsAiError, ValueError):
    """The query failed pre-flight validation (empty, too long, bad lang/page)."""


class RateLimitedError(ScoutsAiError):
    """Upstream returned 429; carries an optional retry hint in seconds."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class UpstreamUnavailableError(ScoutsAiError):
    """Upstream returned 5xx or the network request failed."""


class ApiError(ScoutsAiError):
    """Upstream returned a structured error envelope (4xx other than 429)."""

    def __init__(self, message: str, *, code: str | None = None, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
