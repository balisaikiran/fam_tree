# Family-graph service production image.
# Non-root user, port 8080, gunicorn + uvicorn workers for proper multi-worker
# serving. The base image is pinned to an internal registry tag — change the
# digest/tag when promoting through environments.

FROM ht227nkhrv01.corestg.ae/nkptools/familytree-backend:1.0.0

ARG APP_USER=appuser
RUN addgroup --system ${APP_USER} && adduser --system --ingroup ${APP_USER} ${APP_USER}

WORKDIR /app

COPY ./app ./app

# Static dirs for person avatars (if served from disk) + log dir for the
# RotatingFileHandler in utill/LoggingHandler.py. /app/logs MUST exist and
# be writable by appuser before the first log line; otherwise the handler
# silently falls back to console-only.
RUN mkdir -p app/static/img/citizen app/static/img/resident app/logs \
    && chown -R ${APP_USER}:${APP_USER} /app

USER ${APP_USER}

EXPOSE 8080

# Probe liveness (/healthcheck). Readiness is exposed at /readiness and
# should be polled by the orchestrator, not the Docker HEALTHCHECK.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthcheck', timeout=2)" || exit 1

# gunicorn manages the workers; uvicorn workers handle the ASGI protocol.
# Tune --workers via WEB_CONCURRENCY in your deployment manifest, not here.
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
