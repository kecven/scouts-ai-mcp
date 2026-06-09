# scouts-ai-mcp Dockerfile
# Used by Glama's automated sandbox build (Firecracker microVM).
# Build context = repo root.

FROM python:3.11-slim

# Build-time metadata
LABEL org.opencontainers.image.title="scouts-ai-mcp" \
      org.opencontainers.image.description="MCP server exposing the SCOUTS-AI web search API as a single web_search tool for AI agents." \
      org.opencontainers.image.source="https://github.com/kecven/scouts-ai-mcp" \
      org.opencontainers.image.homepage="https://scouts-ai.com" \
      org.opencontainers.image.licenses="MIT"

# Create a non-root user.
RUN groupadd --system --gid 1001 scouts && \
    useradd  --system --uid 1001 --gid scouts --create-home --shell /usr/sbin/nologin scouts

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Drop privileges.
USER scouts

# Default transport: stdio (MCP standard).
ENTRYPOINT ["scouts-ai-mcp"]

# For HTTP transport, override with:
#   docker run --rm kecven/scouts-ai-mcp scouts-ai-mcp --transport http --host 0.0.0.0 --port 8765