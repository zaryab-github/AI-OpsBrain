#!/usr/bin/env bash
# Start/stop throwaway PostgreSQL + Valkey containers for the backend integration tests.
#   scripts/dev/test-services.sh up|down
set -euo pipefail
case "${1:-up}" in
  up)
    docker run -d --rm --name opsbrain-test-pg -e POSTGRES_PASSWORD=opsbrain-test -p 127.0.0.1:55432:5432 \
      pgvector/pgvector:0.8.0-pg16 >/dev/null
    docker run -d --rm --name opsbrain-test-valkey -p 127.0.0.1:56379:6379 \
      valkey/valkey:8.1-alpine valkey-server --requirepass opsbrain-test >/dev/null
    for _ in $(seq 1 60); do
      docker exec opsbrain-test-pg pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1 && break
      sleep 1
    done
    echo "PostgreSQL on 127.0.0.1:55432, Valkey on 127.0.0.1:56379"
    ;;
  down)
    docker rm -f opsbrain-test-pg opsbrain-test-valkey >/dev/null 2>&1 || true
    ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
