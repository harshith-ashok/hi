# Backend: `hi --voice-daemon` (HTTP + AG-UI SSE on :8765).
# Linux image — macOS-only tools (Bluetooth/volume/screen control) and voice are
# not available inside it; run `hi` natively for those.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

# MCP servers the agents use: GitHub's (a static Go binary, copied out of its
# official image so no Docker-in-Docker is needed) and `fetch` (installed now so
# the first request doesn't wait on a download).
COPY --from=ghcr.io/github/github-mcp-server /server/github-mcp-server /usr/local/bin/github-mcp-server
RUN UV_TOOL_BIN_DIR=/usr/local/bin uv tool install mcp-server-fetch

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HI_HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-group desktop --no-install-project

COPY hi ./hi
COPY README.md ./
RUN uv sync --frozen --no-dev --no-group desktop

EXPOSE 8765
CMD ["hi", "--voice-daemon"]
