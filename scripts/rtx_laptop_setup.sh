#!/usr/bin/env bash
# Run ON the RTX laptop (Linux/WSL shown; on Windows set the same variables with `setx` and restart Ollama).
# Keeps models resident and makes the 16GB GPU go further.
set -euo pipefail

export OLLAMA_HOST=0.0.0.0:11434        # reachable over Tailscale
export OLLAMA_KEEP_ALIVE=-1             # never unload
export OLLAMA_MAX_LOADED_MODELS=2       # gemma resident; gpt-oss:20b swaps in for big tasks
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0        # halves KV memory
export OLLAMA_CONTEXT_LENGTH=8192       # raise only where needed; big contexts eat VRAM

for m in gemma4:e4b gpt-oss:20b; do ollama pull "$m"; done
ollama serve
