"""Shared test fixtures."""

from __future__ import annotations

import httpx
import pytest

from scouts_ai_mcp.config import Config
from scouts_ai_mcp.client import ScoutsAiClient


@pytest.fixture
def config() -> Config:
    return Config(
        base_url="https://scouts-ai.test",
        timeout_s=2.0,
        user_agent="scouts-ai-mcp-tests",
        default_lang="en",
        max_query_length=512,
        max_page=10,
    )


@pytest.fixture
def http_client() -> httpx.Client:
    return httpx.Client(
        base_url="https://scouts-ai.test",
        headers={"User-Agent": "scouts-ai-mcp-tests", "Accept": "application/json"},
    )


@pytest.fixture
def client(config: Config, http_client: httpx.Client) -> ScoutsAiClient:
    return ScoutsAiClient(config=config, http_client=http_client)


@pytest.fixture
def trusted_config() -> Config:
    return Config(
        base_url="https://scouts-ai.test",
        timeout_s=2.0,
        user_agent="scouts-ai-mcp-tests",
        default_lang="en",
        max_query_length=512,
        max_page=10,
        internal_token="shared-secret-xyz",
    )


@pytest.fixture
def trusted_http_client() -> httpx.Client:
    # Intentionally NO `X-Internal-Token` header. The test that uses this
    # fixture proves that ScoutsAiClient adds the header from
    # `config.internal_token`, not that the underlying httpx client carries it.
    return httpx.Client(
        base_url="https://scouts-ai.test",
        headers={
            "User-Agent": "scouts-ai-mcp-tests",
            "Accept": "application/json",
        },
    )


@pytest.fixture
def trusted_client(trusted_config: Config, trusted_http_client: httpx.Client) -> ScoutsAiClient:
    return ScoutsAiClient(config=trusted_config, http_client=trusted_http_client)
