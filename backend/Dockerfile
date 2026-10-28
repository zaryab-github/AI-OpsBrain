# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN python -m venv /venv && /venv/bin/pip install --upgrade pip && /venv/bin/pip install .

FROM python:3.12-slim-bookworm
ENV PATH=/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 opsbrain \
 && useradd --system --uid 10001 --gid opsbrain --home-dir /app --shell /usr/sbin/nologin opsbrain
COPY --from=build /venv /venv
WORKDIR /app
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root app ./app
USER opsbrain
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=4).status == 200 else 1)"
# One process: the API is async, argon2 runs in a thread pool, and Prometheus metrics stay per-process accurate.
# Caddy overwrites X-Forwarded-For with the real client address, and only Caddy can reach this port.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
