# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# The edge: Caddy terminates TLS, serves the UI and proxies /api to the API service.
FROM caddy:2.10.0-alpine
RUN addgroup -S -g 10001 opsbrain && adduser -S -D -H -u 10001 -G opsbrain opsbrain
COPY --from=build /src/dist /srv
ENV XDG_CONFIG_HOME=/config XDG_DATA_HOME=/data
USER opsbrain
