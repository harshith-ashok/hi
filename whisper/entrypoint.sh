#!/bin/sh
# Download the model once (cached in the /models volume), then serve it.
set -e
model="/models/ggml-${WHISPER_MODEL}.bin"
if [ ! -s "$model" ]; then
  curl -fL -o "$model.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${WHISPER_MODEL}.bin"
  mv "$model.part" "$model"
fi
exec whisper-server -m "$model" --host 0.0.0.0 --port 8083
