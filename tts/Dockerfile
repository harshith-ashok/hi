# GPU text-to-speech: Hugging Face's gradium/phonon-40m-en (Phonon), for machines where Ollama's
# `phonon` has no CUDA build. Needs HF_TOKEN (the model is gated). Started with
# `docker compose --profile gpu up -d --build tts`.
FROM python:3.12-slim

# The default Linux torch wheel ships with CUDA support. Phonon needs a recent transformers.
RUN pip install --no-cache-dir --default-timeout=120 --retries 10 torch "transformers>=5.22" soundfile numpy huggingface_hub safetensors

WORKDIR /srv
COPY server.py ./
ENV HF_HOME=/models PYTHONUNBUFFERED=1
EXPOSE 8780
CMD ["python", "server.py"]
