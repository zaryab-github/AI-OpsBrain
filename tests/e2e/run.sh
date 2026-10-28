#!/usr/bin/env bash
# Full lifecycle test of opsbrainctl on a disposable Linux host with Docker (run as root).
# install → smoke checks → status → backup → restore → upgrade → remove (data kept) → reinstall → purge.
# Used by CI on a fresh runner and by tests/e2e/in-docker.sh on a developer machine.
set -Eeuo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
CTL="$REPO/scripts/opsbrainctl"
HOST=opsbrain.test
PORT=18443
WORK=$(mktemp -d)
export OPSBRAIN_BIN_LINK=/usr/local/bin/opsbrainctl

step() { printf '\n\033[1;34m### %s\033[0m\n' "$*"; }
fail() {
  printf '\033[31mE2E FAILED: %s\033[0m\n' "$*" >&2
  docker compose -p opsbrain-core logs --tail 80 2>/dev/null || true
  exit 1
}
dc() { docker compose -p opsbrain-core -f "$REPO/deploy/core/compose.yaml" --env-file /etc/opsbrain/compose.env "$@"; }
user_count() { dc exec -T api opsbrain-admin user-count | tr -d '[:space:]'; }

grep -q " $HOST" /etc/hosts || echo "127.0.0.1 $HOST" >>/etc/hosts
printf 'violet tram under seven bridges\n' >"$WORK/admin.pw"

step "Install core"
"$CTL" install core --hostname "$HOST" --extra-names "127.0.0.1" --http-port 18080 --https-port "$PORT" \
  --admin-user admin --admin-email admin@example.test --admin-password-file "$WORK/admin.pw" ||
  fail "install"
[[ $(stat -c %a /etc/opsbrain/secrets/app.env) == 600 ]] || fail "secrets must be mode 600"
[[ $(stat -c %a /etc/opsbrain/ca/ca.key) == 600 ]] || fail "CA key must be mode 600"
"$CTL" install core >/dev/null || fail "second install must be a no-op"

step "Smoke checks through the TLS proxy"
python3 "$REPO/tests/e2e/smoke.py" "https://$HOST:$PORT" /etc/opsbrain/ca/ca.crt admin "$WORK/admin.pw" ||
  fail "smoke checks"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST:18080/")
[[ $code == 308 || $code == 301 ]] || fail "HTTP must redirect to HTTPS (got $code)"
if curl -s --tls-max 1.1 --cacert /etc/opsbrain/ca/ca.crt "https://$HOST:$PORT/" >/dev/null 2>&1; then
  fail "TLS 1.1 must be refused"
fi

step "Status"
"$CTL" status || true
"$CTL" backup --quiet || fail "first backup"
"$CTL" status || fail "status must be healthy after a backup"

step "Backup and restore"
snap=$(sed -n 's/.*"last_snapshot": *"\([^"]*\)".*/\1/p' /var/lib/opsbrain/backup-status/status.json)
[[ -n $snap ]] || fail "no snapshot id recorded"
[[ $(user_count) == 1 ]] || fail "expected 1 user"
printf 'quiet harbour seven kites\n' | dc exec -T api \
  opsbrain-admin create-admin --username marker --email marker@example.test || fail "create marker user"
[[ $(user_count) == 2 ]] || fail "marker user not created"
if "$CTL" restore "$snap" </dev/null >/dev/null 2>&1; then fail "restore must refuse without typed confirmation"; fi
OPSBRAIN_CONFIRM_PHRASE=restore "$CTL" restore "$snap" || fail "restore"
[[ $(user_count) == 1 ]] || fail "restore did not bring back the earlier state"
"$CTL" backup --list | grep -q pre-restore || fail "safety backup before restore missing"

step "Upgrade (same version: rebuild + migrate + health)"
"$CTL" upgrade --yes || fail "upgrade"
"$CTL" backup --list | grep -q pre-upgrade || fail "pre-upgrade backup missing"

step "Remove keeps data"
"$CTL" remove core --yes || fail "remove"
[[ -z $(docker compose -p opsbrain-core ps -q) ]] || fail "containers still running after remove"
docker volume inspect opsbrain-core_postgres-data >/dev/null || fail "database volume was deleted by plain remove"
[[ -f /etc/opsbrain/secrets/app.env ]] || fail "configuration was deleted by plain remove"
"$CTL" install core --admin-password-file "$WORK/admin.pw" || fail "reinstall"
[[ $(user_count) == 1 ]] || fail "data not preserved across remove/reinstall"
python3 "$REPO/tests/e2e/smoke.py" "https://$HOST:$PORT" /etc/opsbrain/ca/ca.crt admin "$WORK/admin.pw" ||
  fail "smoke checks after reinstall"

step "Purge requires confirmation, then deletes data but keeps backups"
if "$CTL" remove core --purge --no-final-backup </dev/null >/dev/null 2>&1; then fail "purge must refuse without confirmation"; fi
docker volume inspect opsbrain-core_postgres-data >/dev/null || fail "refused purge must not delete data"
OPSBRAIN_CONFIRM_PHRASE="purge core" "$CTL" remove core --purge || fail "purge"
if docker volume inspect opsbrain-core_postgres-data >/dev/null 2>&1; then fail "purge left the database volume"; fi
[[ ! -e /etc/opsbrain ]] || fail "purge left /etc/opsbrain"
ls /var/lib/opsbrain/backup/restic/config >/dev/null || fail "purge must keep backups"

rm -rf "$WORK"
printf '\n\033[1;32mE2E LIFECYCLE PASSED\033[0m\n'
