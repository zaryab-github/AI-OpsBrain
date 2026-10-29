# syntax=docker/dockerfile:1
# Builds the web UI and serves it with Caddy (TLS, security headers, /api reverse proxy).
FROM node:22-alpine AS build
WORKDIR /app
# package-lock.json is used when present (reproducible); otherwise npm resolves from package.json.
# Generate it with scripts/lock-deps.sh and commit it.
COPY package.json package-lock.jso[n] ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
# Type checking runs in CI and via `npm run build`; the image build only bundles.
RUN npx vite build

FROM caddy:2-alpine
ARG OBS_VERSION=dev
LABEL org.opencontainers.image.title="obs-proxy" org.opencontainers.image.version="${OBS_VERSION}"
COPY --from=build /app/dist /srv
# The Caddyfile is mounted at runtime from /etc/obs/core/Caddyfile (rendered by obsctl).
EXPOSE 80 443
