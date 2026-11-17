# Image generation: Z-Image-Turbo (default) or FLUX.2 [klein] through Hugging Face diffusers, on CUDA when there is a GPU.
# Speaks the OpenAI image API (POST /v1/images/generations), which is what hi/imagegen.py calls.
# Started with `docker compose --profile gpu up -d --build imagegen`. diffusers is not pinned: both models need a recent
# release, so rebuild to upgrade. On a Mac there is no GPU in Docker: run `python imagegen/server.py` natively (MPS) and
# set IMAGE_URL=http://host.docker.internal:8790.
FROM python:3.12-slim

RUN pip install --no-cache-dir --default-timeout=120 --retries 10 torch diffusers transformers accelerate sentencepiece protobuf pillow safetensors huggingface_hub  # keep in step with requirements.txt

WORKDIR /srv
COPY server.py ./
ENV HF_HOME=/models PYTHONUNBUFFERED=1
EXPOSE 8790
CMD ["python", "server.py"]
