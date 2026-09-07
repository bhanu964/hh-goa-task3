# Container image for the web demo.
#
# The InsightFace model pack (~280 MB) is downloaded at BUILD time, not on
# first request: a cold start would otherwise spend two minutes downloading,
# and the runtime filesystem may be read-only or ephemeral.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    INSIGHTFACE_HOME=/opt/insightface

# libGL/libglib are needed by OpenCV even in the headless build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-web.txt ./
RUN pip install -r requirements-web.txt

COPY . .

# Warm the model cache into the image.
RUN python -c "\
import insightface, os;\
insightface.app.FaceAnalysis(name=os.getenv('FACE_MODEL_PACK','buffalo_l'),\
    allowed_modules=['detection','recognition'],\
    providers=['CPUExecutionProvider'],\
    root=os.getenv('INSIGHTFACE_HOME','/opt/insightface'))" \
    # The downloaded archive is ~280 MB and is redundant once extracted.
    # Only detection and recognition are used; the other three models in the
    # pack are never loaded, so they go too.
    && rm -f /opt/insightface/models/*.zip \
    && rm -f /opt/insightface/models/buffalo_l/1k3d68.onnx \
             /opt/insightface/models/buffalo_l/2d106det.onnx \
             /opt/insightface/models/buffalo_l/genderage.onnx \
    && du -sh /opt/insightface

EXPOSE 8000
CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --timeout-keep-alive 75"]
