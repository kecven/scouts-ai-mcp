# scouts-ai-mcp

Model Context Protocol (MCP) server that exposes the [SCOUTS-AI](https://scouts-ai.com/) web search API as a single `web_search` tool for AI agents, LLM apps, answer engines and GEO workflows.

- **One tool, no API key.** Backed by `GET https://scouts-ai.com/api/search`.
- **Drop-in for Claude Desktop, Cursor, Open WebUI, Continue, Cline** and any MCP host.
- **Python ≥ 3.10**, `fastmcp` v2, `httpx`.
- **MIT licensed.**

## Install

```bash
pip install scouts-ai-mcp
```

## Run (stdio)

```bash
scouts-ai-mcp
```

That's it. Wire it into your MCP host of choice — for example, Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "scouts-ai": {
      "command": "scouts-ai-mcp"
    }
  }
}
```

## Run (HTTP)

For remote MCP hosts and self-hosted bridges:

```bash
scouts-ai-mcp --transport http --host 127.0.0.1 --port 8765
```

## Tool: `web_search`

| Parameter | Type   | Default | Description                                  |
| --------- | ------ | ------- | -------------------------------------------- |
| `query`   | string | —       | Search query, 1–512 chars.                   |
| `lang`    | string | `en`    | BCP-47 language code (e.g. `en`, `en-US`).   |
| `page`    | int    | `1`     | 1-based page number, 1–10.                   |

Returns a compact JSON object mirroring the SCOUTS-AI response shape:

```json
{
  "query": "rust async runtime",
  "lang": "en",
  "page": 1,
  "pageSize": 10,
  "cached": false,
  "tookMs": 412,
  "results": [
    {
      "title": "Tokio - An asynchronous runtime for Rust",
      "url": "https://tokio.rs/",
      "content": "Tokio is an asynchronous runtime for the Rust programming language...",
      "publishedAt": "2025-11-14T00:00:00Z",
      "engine": "duckduckgo"
    }
  ]
}
```

### Error handling

The tool raises `ToolError` (rendered as an MCP tool error) when:

- The query is empty/too long or `lang`/`page` are invalid → invalid arguments.
- The upstream returns `429` → rate limit exceeded; honors `Retry-After` when present.
- The upstream returns `5xx` or the network call fails → SCOUTS-AI temporarily unavailable.
- The upstream returns a structured `4xx` error envelope → forwards the code and message.

## Configuration

All settings are environment variables. Defaults match the public SCOUTS-AI deployment.

| Variable                   | Default                  | Description                              |
| -------------------------- | ------------------------ | ---------------------------------------- |
| `SCOUTS_AI_BASE_URL`       | `https://scouts-ai.com`  | Base URL of the SCOUTS-AI API.           |
| `SCOUTS_AI_TIMEOUT_S`      | `5.0`                    | HTTP timeout in seconds (0.1–60).        |
| `SCOUTS_AI_USER_AGENT`     | `scouts-ai-mcp/0.1.2`    | User-Agent header.                       |
| `SCOUTS_AI_DEFAULT_LANG`   | `en`                     | Default `lang` when the tool omits it.   |
| `SCOUTS_AI_MAX_QUERY_LENGTH` | `512`                  | Reject queries longer than this.         |
| `SCOUTS_AI_MAX_PAGE`       | `10`                     | Reject page numbers above this.          |

## Development

```bash
git clone https://github.com/scouts-ai/scouts-ai-mcp.git
cd scouts-ai-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Publishing to PyPI

One-time setup, then publish in three commands.

### 1. Create a PyPI account

- Register at [pypi.org/account/register](https://pypi.org/account/register/).
- Account settings → **Add 2FA** (required for uploads; TOTP authenticator or WebAuthn).
- Account settings → **API tokens** → **Add API token**.
  - Name: `scouts-ai-mcp`
  - Scope: `Entire account` (or limit to the project after first upload)
  - Copy the token (`pypi-...`) — shown only once.

Verify the project name is free: open `https://pypi.org/project/scouts-ai-mcp/`
(404 = available).

### 2. Install publishing tools

```bash
pip install build twine
```

### 3. Build and upload

```bash
python -m build
python -m twine upload dist/*
```

- Username: `__token__`
- Password: your `pypi-...` API token

For subsequent releases: bump `version` in `pyproject.toml`, then repeat step 3.

### Optional: automate via GitHub Actions (Trusted Publishing)

Recommended for long-term maintenance — no API token in CI.

1. PyPI → Project → Publishing → Add a new pending publisher:
   - Owner: `scouts-ai`
   - Repository: `scouts-ai-mcp`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
2. Add `.github/workflows/release.yml` that runs `python -m build && python -m twine publish-dist`
   on tag push (`v*`).
3. Cut a release: `git tag v0.1.0 && git push --tags`.

## License

MIT — see [LICENSE](./LICENSE).
