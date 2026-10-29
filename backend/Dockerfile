# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ARG OBS_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS build
WORKDIR /build
# requirements.txt (the pinned lock) is used when present; otherwise requirements.in.
# Generate the lock with scripts/lock-deps.sh and commit it for reproducible builds.
COPY requirements.in requirements.tx[t] ./
RUN python -m venv /opt/venv \
 && if [ -f requirements.txt ]; then R=requirements.txt; else R=requirements.in; fi \
 && echo "installing from $R" && /opt/venv/bin/pip install -r "$R"

FROM base AS runtime
ARG OBS_VERSION=dev
LABEL org.opencontainers.image.title="obs-backend" org.opencontainers.image.version="${OBS_VERSION}"
RUN groupadd --system --gid 10001 obs && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin obs
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" OBS_VERSION=${OBS_VERSION}
WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
