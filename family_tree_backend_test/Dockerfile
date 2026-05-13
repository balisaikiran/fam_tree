# syntax=docker/dockerfile:1.6
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Run as a non-root user to satisfy hardened-baseline pod security standards.
RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

# Install Python deps first so requirements.txt churn doesn't bust the
# layer that holds the actual app code.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER app

# Liveness/readiness probes are exposed at /healthcheck and /readiness.
EXPOSE 8080

# gunicorn manages the workers; uvicorn workers handle the ASGI protocol.
# Tune --workers via WEB_CONCURRENCY (default 4) and timeouts via env in
# your deployment manifest, not here.
ENV WEB_CONCURRENCY=4 \
    GUNICORN_TIMEOUT=60 \
    GUNICORN_GRACEFUL_TIMEOUT=30

CMD ["sh", "-c", "exec gunicorn app.main:app \
     -k uvicorn.workers.UvicornWorker \
     -w ${WEB_CONCURRENCY} \
     -b 0.0.0.0:8080 \
     --timeout ${GUNICORN_TIMEOUT} \
     --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT} \
     --access-logfile - \
     --error-logfile -"]
