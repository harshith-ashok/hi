# Backend: `hi --voice-daemon` (HTTP + AG-UI SSE on :8765).
# Linux image — macOS-only tools (Bluetooth/volume/screen control) and voice are
# not available inside it; run `hi` natively for those.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HI_HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-group desktop --no-install-project

COPY hi ./hi
COPY README.md ./
RUN uv sync --frozen --no-dev --no-group desktop

EXPOSE 8765
CMD ["hi", "--voice-daemon"]
