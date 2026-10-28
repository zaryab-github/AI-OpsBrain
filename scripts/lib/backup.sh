# shellcheck shell=bash
# Encrypted backups with restic (run from its container, nothing to install on the host).

RESTIC_IMAGE="restic/restic:0.18.0"

restic_run() {
  # restic_run [docker-run-args...] -- restic-args...
  local env_file=$OPSBRAIN_ETC/secrets/backup.env repo
  [[ -f $env_file ]] || die "Backup configuration missing: $env_file"
  repo=$(env_get "$env_file" RESTIC_REPOSITORY)
  local docker_args=(--rm -i --env-file "$env_file" --hostname "$(env_get "$OPSBRAIN_ETC/compose.env" OPSBRAIN_HOSTNAME)")
  if [[ $repo == /* ]]; then
    install -d -m 0700 "$repo"
    docker_args+=(-v "$repo:$repo")
  fi
  while [[ $# -gt 0 && $1 != -- ]]; do
    docker_args+=("$1")
    shift
  done
  [[ ${1:-} == -- ]] && shift
  docker run "${docker_args[@]}" "$RESTIC_IMAGE" "$@"
}

restic_ensure_repo() {
  if ! restic_run -- cat config >/dev/null 2>&1; then
    info "Initialising backup repository $(env_get "$OPSBRAIN_ETC/secrets/backup.env" RESTIC_REPOSITORY)"
    restic_run -- init >/dev/null
  fi
}

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' '; }

backup_write_status() {
  local result=$1 snapshot=${2:-} error=${3:-} f prev_success now
  f=$OPSBRAIN_VAR/backup-status/status.json
  now=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
  prev_success=$(sed -n 's/.*"last_success": *"\([^"]*\)".*/\1/p' "$f" 2>/dev/null || true)
  [[ $result == success ]] && prev_success=$now
  install -d -m 0755 "$OPSBRAIN_VAR/backup-status"
  local repo
  repo=$(env_get "$OPSBRAIN_ETC/secrets/backup.env" RESTIC_REPOSITORY | sed 's#//[^@/]*@#//***@#')
  cat >"$f.tmp" <<EOF
{"last_result": "$result", "last_attempt": "$now", "last_success": "${prev_success}", "last_snapshot": "$snapshot", "last_error": "$(json_escape "$error")", "repository": "$repo"}
EOF
  chmod 0644 "$f.tmp"
  mv "$f.tmp" "$f"
}

cmd_backup() {
  require_root backup
  check_docker
  if [[ ${BACKUP_LIST:-0} == 1 ]]; then
    restic_run -- snapshots
    return
  fi
  if [[ ${BACKUP_CHECK:-0} == 1 ]]; then
    restic_run -- check
    return
  fi
  module_installed core || die "Core is not installed; nothing to back up."
  local stage ts tag=${BACKUP_TAG:-manual}
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  stage=$OPSBRAIN_VAR/backup/staging/$ts
  install -d -m 0700 "$stage/core"
  # shellcheck disable=SC2064
  trap "rm -rf '$stage'" EXIT

  local err=""
  {
    [[ ${QUIET:-0} == 1 ]] || info "Dumping PostgreSQL"
    compose core exec -T postgres pg_dump -U postgres -d opsbrain -Fc >"$stage/core/postgres.dump" ||
      err="pg_dump failed"
    if [[ -z $err ]]; then
      cp -a "$OPSBRAIN_ETC" "$stage/etc" || err="copying configuration failed"
      printf '{"version": "%s", "hostname": "%s", "created": "%s", "modules": "%s"}\n' "$(version)" \
        "$(env_get "$OPSBRAIN_ETC/compose.env" OPSBRAIN_HOSTNAME)" "$ts" "$(installed_modules | tr '\n' ' ')" \
        >"$stage/manifest.json"
    fi
  }
  if [[ -z $err ]]; then
    restic_ensure_repo || err="cannot open or initialise the backup repository"
  fi
  local out=""
  if [[ -z $err ]]; then
    [[ ${QUIET:-0} == 1 ]] || info "Writing encrypted snapshot"
    if ! out=$(restic_run -v "$stage:/opsbrain-backup:ro" -- backup /opsbrain-backup \
      --tag opsbrain --tag "$tag" --tag "v$(version)" --json 2>&1); then
      err="restic backup failed: $(printf '%s' "$out" | tail -n 3)"
    fi
  fi
  if [[ -n $err ]]; then
    backup_write_status failure "" "$err"
    die "Backup failed: $err"
  fi
  local snap
  snap=$(printf '%s' "$out" | grep -o '"snapshot_id":"[0-9a-f]*"' | tail -n1 | cut -d'"' -f4)
  local env_file=$OPSBRAIN_ETC/secrets/backup.env
  restic_run -- forget --tag opsbrain --prune --quiet \
    --keep-daily "$(env_get "$env_file" KEEP_DAILY || echo 7)" \
    --keep-weekly "$(env_get "$env_file" KEEP_WEEKLY || echo 4)" \
    --keep-monthly "$(env_get "$env_file" KEEP_MONTHLY || echo 6)" >/dev/null ||
    warn "Pruning old snapshots failed; the new backup is still complete."
  backup_write_status success "${snap:0:8}"
  ok "Backup complete: snapshot ${snap:0:8} (tag $tag)"
}

cmd_restore() {
  require_root restore
  check_docker
  module_installed core || die "Install core first (sudo opsbrainctl install core), then restore into it."
  local snapshot=${RESTORE_SNAPSHOT:-latest}
  restic_run -- snapshots "$snapshot" >/dev/null 2>&1 || die "Snapshot '$snapshot' not found. List them with: opsbrainctl backup --list"
  restic_run -- snapshots "$snapshot"
  cat <<EOF
${C_YEL}Restoring replaces the current platform database (users, roles, settings, audit log, …) with the
contents of snapshot '$snapshot'.$([[ ${RESTORE_CONFIG:-0} == 1 ]] && echo " Configuration in $OPSBRAIN_ETC is replaced too (the current one is kept in $OPSBRAIN_ETC.pre-restore-*).")${C_OFF}
EOF
  if [[ ${NO_SAFETY_BACKUP:-0} != 1 ]]; then
    info "Taking a safety backup of the current state first"
    BACKUP_TAG=pre-restore cmd_backup
    trap - EXIT
  fi
  confirm_phrase "restore" "The current database will be replaced."

  local work ts
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  work=$OPSBRAIN_VAR/backup/restore-$ts
  install -d -m 0700 "$work"
  info "Extracting snapshot"
  restic_run -v "$work:/restore" -- restore "$snapshot" --target /restore >/dev/null
  local data=$work/opsbrain-backup
  [[ -f $data/core/postgres.dump ]] || die "Snapshot has no core database dump"

  if [[ ${RESTORE_CONFIG:-0} == 1 ]]; then
    info "Restoring configuration (current one saved to $OPSBRAIN_ETC.pre-restore-$ts)"
    cp -a "$OPSBRAIN_ETC" "$OPSBRAIN_ETC.pre-restore-$ts"
    cp -a "$data/etc/." "$OPSBRAIN_ETC/"
    # Database role passwords must match the restored secrets.
    compose core up -d postgres
    wait_healthy core 120 || true
    local pg=$OPSBRAIN_ETC/secrets/postgres.env
    compose core exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
      -v sp="$(env_get "$pg" POSTGRES_PASSWORD)" -v op="$(env_get "$pg" OPSBRAIN_DB_OWNER_PASSWORD)" \
      -v ap="$(env_get "$pg" OPSBRAIN_DB_APP_PASSWORD)" >/dev/null <<'EOSQL'
ALTER ROLE postgres PASSWORD :'sp';
ALTER ROLE opsbrain_owner PASSWORD :'op';
ALTER ROLE opsbrain_app PASSWORD :'ap';
EOSQL
  fi

  info "Stopping application services"
  compose core stop web api worker >/dev/null
  info "Restoring database"
  compose core exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q <<'EOSQL'
DROP DATABASE IF EXISTS opsbrain WITH (FORCE);
CREATE DATABASE opsbrain OWNER opsbrain_owner;
REVOKE ALL ON DATABASE opsbrain FROM PUBLIC;
GRANT CONNECT ON DATABASE opsbrain TO opsbrain_owner, opsbrain_app;
\c opsbrain
ALTER SCHEMA public OWNER TO opsbrain_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
  # Restore as the owner role so ownership is right; extensions were created above by the superuser.
  compose core exec -T postgres sh -c 'cat > /tmp/opsbrain.dump' <"$data/core/postgres.dump"
  # shellcheck disable=SC2016 # $? is expanded by the container's shell
  compose core exec -T postgres sh -c \
    'pg_restore -l /tmp/opsbrain.dump | grep -v " EXTENSION " > /tmp/opsbrain.list &&
     pg_restore -U opsbrain_owner -d opsbrain --no-owner --exit-on-error -L /tmp/opsbrain.list /tmp/opsbrain.dump;
     rc=$?; rm -f /tmp/opsbrain.dump /tmp/opsbrain.list; exit $rc' ||
    die "pg_restore failed. The pre-restore safety backup is available: opsbrainctl backup --list"
  compose core exec -T postgres psql -U postgres -d opsbrain -v ON_ERROR_STOP=1 -q \
    -f /docker-entrypoint-initdb.d/grants.sql.inc

  info "Starting services"
  compose core up -d
  wait_healthy core 300 || die "Services did not become healthy after restore; see opsbrainctl logs api"
  compose core exec -T api opsbrain-admin verify-audit || warn "Audit chain verification reported a problem."
  rm -rf "$work"
  ok "Restore of snapshot '$snapshot' complete."
}
