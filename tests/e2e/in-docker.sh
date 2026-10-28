#!/usr/bin/env bash
# Run tests/e2e/run.sh inside a disposable Ubuntu 24.04 "server" (privileged container with its own
# Docker daemon), so the lifecycle test never touches the developer's machine.
set -euo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# On Git Bash (Windows) Docker needs a Windows path, and MSYS must not rewrite container paths.
HOST_REPO=$(cd "$REPO" && (pwd -W 2>/dev/null || pwd))
export MSYS_NO_PATHCONV=1

docker build -t opsbrain-e2e-host -f - "$HOST_REPO/tests/e2e" <<'EOF'
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      docker.io docker-compose-v2 docker-buildx openssl curl ca-certificates python3 git iproute2 \
    && rm -rf /var/lib/apt/lists/*
EOF

docker rm -f opsbrain-e2e >/dev/null 2>&1 || true
docker run --name opsbrain-e2e --privileged -d -v "$HOST_REPO:/src:ro" --tmpfs /run --tmpfs /tmp \
  opsbrain-e2e-host sleep infinity >/dev/null
trap 'docker rm -f opsbrain-e2e >/dev/null 2>&1 || true' EXIT

docker exec opsbrain-e2e bash -c '
  set -e
  (dockerd >/var/log/dockerd.log 2>&1 &)
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
  # Copy the working tree (as a production checkout would be) and normalise ownership.
  mkdir -p /opt && cp -a /src /opt/opsbrain && chown -R root:root /opt/opsbrain
  rm -rf /opt/opsbrain/backend/.venv /opt/opsbrain/frontend/node_modules /opt/opsbrain/frontend/dist
  bash /opt/opsbrain/tests/e2e/run.sh
'
