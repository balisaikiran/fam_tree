# Family-graph service production image.
# Mirrors bi-dashboards-service/prod.Dockerfile: non-root user, port 8080,
# entrypoint via uvicorn. Update the base image tag to a pinned version
# before promoting to a non-dev environment — :latest is fine for now but
# should be pinned to a digest or semver for prod (e.g. ...:1.4.2).

FROM ht227nkhrv01.corestg.ae/nkptools/familytree-backend:1.0.0

ARG APP_USER=appuser
RUN addgroup --system ${APP_USER} && adduser --system --ingroup ${APP_USER} ${APP_USER}

WORKDIR /app

COPY ./app ./app

# Create static dirs if your deployment serves person avatars from disk.
RUN mkdir -p app/static/img/citizen app/static/img/resident \
    && chown -R ${APP_USER}:${APP_USER} /app

USER ${APP_USER}

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthcheck', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
