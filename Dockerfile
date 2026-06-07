FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /application

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

RUN pip install \
    accelerate==1.13.0 \
    bitsandbytes==0.49.2 \
    Flask==2.3.2 \
    huggingface_hub==1.16.1 \
    peft==0.19.1 \
    requests==2.34.2 \
    safetensors==0.7.0 \
    torch==2.12.0 \
    transformers==5.8.1 \
    Werkzeug==2.3.6

COPY app.py model_service.py ./

EXPOSE 9000 9001