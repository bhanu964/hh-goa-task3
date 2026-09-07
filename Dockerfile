# Container image for the web demo.
#
# Runs on Hugging Face Spaces (Docker SDK), Render, Fly.io or locally.
#
# Two things are done at BUILD time rather than on first request:
#   * the InsightFace model pack (~280 MB) is downloaded and pruned, so a cold
#     start does not spend minutes fetching it over the network;
#   * a non-root user (uid 1000) is created, because Hugging Face Spaces runs
#     containers as that uid and anything the app writes must be owned by it.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    INSIGHTFACE_HOME=/opt/insightface \
    OUTPUT_DIR=/tmp/hhgoa-output \
    PORT=7860

# libGL/libglib are needed by OpenCV even in the headless build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt requirements-web.txt ./
RUN pip install -r requirements-web.txt

COPY . .

# Warm the model cache into the image, then drop what is never loaded:
# the archive is redundant once extracted, and only detection + recognition
# are used out of the five models in the pack.
COPY scripts/fetch_models.py /tmp/fetch_models.py

# Warm the model cache into the image, then drop what is never loaded: the
# archive is redundant once extracted, and only detection + recognition are
# used out of the five models in the pack. The fetch retries — a transient
# GitHub failure should not break a reproducible build.
RUN python /tmp/fetch_models.py \
    && rm -f /opt/insightface/models/*.zip \
    && rm -f /opt/insightface/models/buffalo_l/1k3d68.onnx \
             /opt/insightface/models/buffalo_l/2d106det.onnx \
             /opt/insightface/models/buffalo_l/genderage.onnx \
    && mkdir -p /tmp/hhgoa-output \
    && chown -R appuser:appuser /app /opt/insightface /tmp/hhgoa-output \
    && rm -f /tmp/fetch_models.py \
    && du -sh /opt/insightface

USER appuser

EXPOSE 7860
CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1 --timeout-keep-alive 75"]
