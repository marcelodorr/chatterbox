# Serviço de inferência Chatterbox.
# CPU (padrão):  docker build -f inference/Dockerfile .
# GPU (CUDA):    docker build -f inference/Dockerfile --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 .
FROM python:3.11-slim

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    HF_HUB_DISABLE_TELEMETRY=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch primeiro, do índice certo (CPU por padrão; evita baixar as libs CUDA)
RUN pip install --index-url ${TORCH_INDEX} torch==2.6.0 torchaudio==2.6.0

# Pacote chatterbox (raiz deste repositório)
COPY pyproject.toml README.md LICENSE /opt/chatterbox/
COPY src /opt/chatterbox/src
RUN pip install /opt/chatterbox

COPY inference/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY inference/*.py /app/

EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
