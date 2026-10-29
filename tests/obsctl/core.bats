#!/usr/bin/env bats
load helpers

setup() { setup_sandbox; }
teardown() { teardown_sandbox; }

secret() { cat "${OBS_ETC}/secrets/$1"; }

@test "version prints the VERSION file" {
  run "$OBSCTL" version
  [ "$status" -eq 0 ]
  [[ "$output" == "obsctl $(tr -d '[:space:]' < "${REPO_ROOT}/VERSION")" ]]
}

@test "unknown module is rejected with the list of available modules" {
  run "$OBSCTL" frobnicate status
  [ "$status" -ne 0 ]
  [[ "$output" == *"Modules available in this release: core"* ]]
}

@test "install requires a valid hostname" {
  run "$OBSCTL" core install --no-admin --no-timers --backup-keep 0
  [ "$status" -ne 0 ]
  [[ "$output" == *"valid --hostname is required"* ]]
  run "$OBSCTL" core install --hostname 'bad host!' --no-admin --backup-keep 0
  [ "$status" -ne 0 ]
}

@test "install generates unique, non-empty secrets that are not world readable" {
  do_install
  [ "$status" -eq 0 ]
  for s in core_db_password core_jwt_secret core_field_key core_audit_hmac_key core_metrics_token backup_passphrase; do
    [ -s "${OBS_ETC}/secrets/${s}" ]
    perms="$(stat -c %a "${OBS_ETC}/secrets/${s}")"
    [ "$perms" = "440" ]
  done
  # all different from each other
  n="$(for s in core_db_password core_jwt_secret core_field_key core_audit_hmac_key core_metrics_token backup_passphrase; do secret "$s"; echo; done | sort -u | wc -l)"
  [ "$n" -eq 6 ]
  # no placeholder / default values
  ! grep -rqiE 'changeme|password123|admin|secret$' "${OBS_ETC}/secrets"
}

@test "the field encryption key is a valid 32-byte url-safe base64 key" {
  do_install
  [ "$status" -eq 0 ]
  key="$(secret core_field_key)"
  [ "${#key}" -eq 44 ]
  decoded="$(printf '%s' "$key" | tr '_-' '/+' | base64 -d | wc -c)"
  [ "$decoded" -eq 32 ]
}

@test "install writes core.env and a Caddyfile for the chosen hostname" {
  do_install
  [ "$status" -eq 0 ]
  grep -q '^OBS_HOSTNAME=obs.test.local$' "${OBS_ETC}/core.env"
  grep -q '^OBS_HTTPS_PORT=18443$' "${OBS_ETC}/core.env"
  grep -q 'https://obs.test.local {' "${OBS_ETC}/core/Caddyfile"
  grep -q 'tls internal' "${OBS_ETC}/core/Caddyfile"
  grep -q 'default_sni obs.test.local' "${OBS_ETC}/core/Caddyfile"
  grep -q 'redir https://{host}:18443{uri}' "${OBS_ETC}/core/Caddyfile"
  ! grep -q '@@' "${OBS_ETC}/core/Caddyfile"
}

@test "install builds, migrates, starts and waits for healthy services" {
  do_install
  [ "$status" -eq 0 ]
  log="$(docker_log)"
  [[ "$log" == *"build --pull"* ]]
  [[ "$log" == *"run --rm --no-deps -T migrate"* ]]
  [[ "$log" == *" up -d"* ]]
}

@test "install is idempotent: secrets and config are never regenerated" {
  do_install
  [ "$status" -eq 0 ]
  before="$(sha256sum "${OBS_ETC}"/secrets/* "${OBS_ETC}/core.env" | sha256sum)"
  run "$OBSCTL" core install --no-admin --no-timers --no-build
  [ "$status" -eq 0 ]
  [[ "$output" == *"reusing it"* ]]
  after="$(sha256sum "${OBS_ETC}"/secrets/* "${OBS_ETC}/core.env" | sha256sum)"
  [ "$before" = "$after" ]
}

@test "install creates the first administrator only when no users exist" {
  FAKE_HAS_USERS=0 run "$OBSCTL" core install --hostname obs.test.local --http-port 18080 --https-port 18443 \
    --backup-keep 0 --no-timers --admin-user alice --admin-generate-password
  [ "$status" -eq 0 ]
  [[ "$(docker_log)" == *"create-admin --username alice --generate"* ]]
}

@test "admin password is passed through stdin, never as an argument" {
  FAKE_HAS_USERS=0 run bash -c "printf 'S3cret-Passw0rd-xyz' | '$OBSCTL' core install --hostname obs.test.local --http-port 18080 --https-port 18443 --backup-keep 0 --no-timers --admin-user alice --admin-password-stdin"
  [ "$status" -eq 0 ]
  log="$(docker_log)"
  [[ "$log" == *"create-admin --username alice --password-stdin"* ]]
  [[ "$log" != *"S3cret-Passw0rd-xyz"* ]]
}

@test "install with an invalid admin username is refused" {
  FAKE_HAS_USERS=0 run "$OBSCTL" core install --hostname obs.test.local --http-port 18080 --https-port 18443 \
    --backup-keep 0 --no-timers --admin-user 'Bad User' --admin-generate-password
  [ "$status" -ne 0 ]
  [[ "$output" == *"administrator username must be"* ]]
}

@test "tls custom needs readable cert and key" {
  do_install --tls custom
  [ "$status" -ne 0 ]
  [[ "$output" == *"--cert and --key"* ]]
}

@test "tls acme refuses an IP address" {
  run "$OBSCTL" core install --hostname 10.1.2.3 --tls acme --no-admin --backup-keep 0
  [ "$status" -ne 0 ]
  [[ "$output" == *"public DNS name"* ]]
}

@test "Caddyfile: acme mode has no tls directive and carries the contact e-mail" {
  run "$OBSCTL" core install --hostname obs.example.com --tls acme --acme-email ops@example.com --no-admin --no-timers --backup-keep 0
  [ "$status" -eq 0 ]
  ! grep -q 'tls internal' "${OBS_ETC}/core/Caddyfile"
  grep -q 'email ops@example.com' "${OBS_ETC}/core/Caddyfile"
}

@test "Caddyfile: custom mode points at the installed certificate" {
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "${TMP}/k.pem" -out "${TMP}/c.pem" -subj "/CN=obs.test.local" -days 2 2>/dev/null
  do_install --tls custom --cert "${TMP}/c.pem" --key "${TMP}/k.pem"
  [ "$status" -eq 0 ]
  grep -q 'tls /etc/caddy/certs/server.crt /etc/caddy/certs/server.key' "${OBS_ETC}/core/Caddyfile"
  [ "$(stat -c %a "${OBS_ETC}/core/certs/server.key")" = "600" ]
}

@test "Caddyfile: IPv6 literal hostnames are bracketed" {
  run "$OBSCTL" core install --hostname fd00::10 --no-admin --no-timers --backup-keep 0
  [ "$status" -eq 0 ]
  grep -q 'https://\[fd00::10\] {' "${OBS_ETC}/core/Caddyfile"
}

@test "Caddyfile: renders a file the real caddy accepts (skipped when caddy is absent)" {
  command -v caddy >/dev/null || skip "caddy binary not available"
  do_install
  [ "$status" -eq 0 ]
  run caddy validate --config "${OBS_ETC}/core/Caddyfile" --adapter caddyfile
  [ "$status" -eq 0 ]
  # the formatted output must not differ in meaning: metrics stays blocked
  grep -q 'handle /metrics\*' "${OBS_ETC}/core/Caddyfile"
}

@test "status reports not installed with exit code 3" {
  run "$OBSCTL" core status
  [ "$status" -eq 3 ]
  run "$OBSCTL" core status --json
  [ "$status" -eq 3 ]
  [[ "$output" == '{"module":"core","installed":false}' ]]
}

@test "status --json is valid JSON and reflects health" {
  do_install
  run "$OBSCTL" core status --json
  [ "$status" -eq 0 ]
  echo "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["healthy"] is True; assert set(d["services"])=={"postgres","api","worker","proxy"}'
  FAKE_UNHEALTHY=api run "$OBSCTL" core status --json
  [ "$status" -eq 1 ]
  echo "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["healthy"] is False; assert d["services"]["api"]=="running/unhealthy"'
}

@test "watchdog: healthy services but no backup yet is a warning (exit 1)" {
  do_install
  run "$OBSCTL" core watchdog
  [ "$status" -eq 1 ]
  [[ "$output" == *"container.api"*"ok"* ]]
  [[ "$output" == *"backup.recent"*"warn"* ]]
}

@test "watchdog: an unhealthy container is critical (exit 2)" {
  do_install
  FAKE_UNHEALTHY=api run "$OBSCTL" core watchdog
  [ "$status" -eq 2 ]
  [[ "$output" == *"container.api"*"crit"* ]]
}

@test "watchdog reports its results to the application" {
  do_install
  run "$OBSCTL" core watchdog --quiet
  [ -s "${FAKE_DOCKER_LOG}.selfmon" ]
  grep -q $'^container.postgres\tok\t' "${FAKE_DOCKER_LOG}.selfmon"
}

@test "backup produces an encrypted, verified file and a checksum" {
  do_install
  run "$OBSCTL" core backup
  [ "$status" -eq 0 ]
  f="$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)"
  [ "$(stat -c %a "$f")" = "600" ]
  [ -s "${f}.sha256" ]
  # not plaintext
  ! grep -qa "PGDUMP-CONTENT" "$f"
  # decrypts with the install passphrase and contains the expected members
  gpg --batch --quiet --pinentry-mode loopback --passphrase-file "${OBS_ETC}/secrets/backup_passphrase" \
      --decrypt -o "${TMP}/b.tar" "$f"
  tar -tf "${TMP}/b.tar" | grep -q '/db.dump$'
  tar -tf "${TMP}/b.tar" | grep -q '/config/secrets/core_jwt_secret$'
  tar -tf "${TMP}/b.tar" | grep -q '/MANIFEST$'
  # the database password and the backup passphrase are NOT inside the archive
  ! tar -tf "${TMP}/b.tar" | grep -q 'core_db_password'
  ! tar -tf "${TMP}/b.tar" | grep -q 'backup_passphrase'
}

@test "backup does not leave temporary work directories behind" {
  do_install
  run "$OBSCTL" core backup --quiet
  [ "$status" -eq 0 ]
  [ -z "$(find "${OBS_BACKUP_DIR}" -maxdepth 1 -name '.work.*')" ]
}

@test "backup with keep=0 never prunes" {
  do_install
  for i in 1 2 3; do run "$OBSCTL" core backup --quiet --keep 0; [ "$status" -eq 0 ]; sleep 1.1; done
  [ "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg | wc -l)" -eq 3 ]
}

@test "backup with keep=2 prunes only older backups" {
  do_install
  for i in 1 2 3; do run "$OBSCTL" core backup --quiet --keep 2; [ "$status" -eq 0 ]; sleep 1.1; done
  [ "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg | wc -l)" -eq 2 ]
}

@test "backup refuses when postgres is not healthy" {
  do_install
  FAKE_UNHEALTHY=postgres run "$OBSCTL" core backup
  [ "$status" -ne 0 ]
  [[ "$output" == *"postgres is not running/healthy"* ]]
  [ -z "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg 2>/dev/null)" ]
}

@test "restore requires the exact typed confirmation and changes nothing without it" {
  do_install
  run "$OBSCTL" core backup --quiet
  f="$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)"
  : > "$FAKE_DOCKER_LOG"
  run "$OBSCTL" core restore "$f"
  [ "$status" -ne 0 ]
  [[ "$output" == *"restore core"* ]]
  [[ "$(docker_log)" != *"DROP DATABASE"* ]]
  run "$OBSCTL" core restore "$f" --confirm-restore "yes please"
  [ "$status" -ne 0 ]
  [[ "$(docker_log)" != *"DROP DATABASE"* ]]
}

@test "restore with confirmation takes a safety backup, then replaces the database" {
  do_install
  run "$OBSCTL" core backup --quiet
  f="$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)"
  : > "$FAKE_DOCKER_LOG"
  sleep 1.1
  run "$OBSCTL" core restore "$f" --confirm-restore "restore core"
  [ "$status" -eq 0 ]
  ls "${OBS_BACKUP_DIR}"/obs-core_*pre-restore.tar.gpg
  log="$(docker_log)"
  [[ "$log" == *"DROP DATABASE IF EXISTS obs WITH (FORCE)"* ]]
  [[ "$log" == *"pg_restore"* ]]
  grep -q '^PGDUMP-CONTENT' "${FAKE_DOCKER_LOG}.pg_restore_stdin"
  ls -d "${OBS_ETC}"/pre-restore-*
}

@test "restore keeps this server's database password" {
  do_install
  run "$OBSCTL" core backup --quiet
  f="$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)"
  pw_before="$(secret core_db_password)"
  jwt_before="$(secret core_jwt_secret)"
  echo "garbage" > "${OBS_ETC}/secrets/core_jwt_secret"
  sleep 1.1
  run "$OBSCTL" core restore "$f" --confirm-restore "restore core"
  [ "$status" -eq 0 ]
  [ "$(secret core_db_password)" = "$pw_before" ]
  [ "$(secret core_jwt_secret)" = "$jwt_before" ]
}

@test "restore refuses a tampered backup before touching anything" {
  do_install
  run "$OBSCTL" core backup --quiet
  f="$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)"
  printf 'X' | dd of="$f" bs=1 seek=200 count=1 conv=notrunc 2>/dev/null
  : > "$FAKE_DOCKER_LOG"
  run "$OBSCTL" core restore "$f" --confirm-restore "restore core"
  [ "$status" -ne 0 ]
  [[ "$(docker_log)" != *"DROP DATABASE"* ]]
}

@test "restore refuses the wrong passphrase" {
  do_install
  run "$OBSCTL" core backup --quiet
  f="$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)"
  printf 'not-the-passphrase' > "${TMP}/wrong"
  rm -f "${f}.sha256"
  : > "$FAKE_DOCKER_LOG"
  run "$OBSCTL" core restore "$f" --passphrase-file "${TMP}/wrong" --confirm-restore "restore core"
  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot decrypt"* ]]
  [[ "$(docker_log)" != *"DROP DATABASE"* ]]
}

@test "remove keeps all data, config, secrets and backups" {
  do_install
  run "$OBSCTL" core backup --quiet
  run "$OBSCTL" core remove
  [ "$status" -eq 0 ]
  [[ "$output" == *"data is kept"* ]]
  log="$(docker_log)"
  [[ "$log" == *" down --remove-orphans"* ]]
  [[ "$log" != *"--volumes"* ]]
  [[ "$log" != *" -v"* ]]
  [ -f "${OBS_ETC}/core.env" ]
  [ -s "${OBS_ETC}/secrets/core_db_password" ]
  [ -n "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)" ]
}

@test "install after remove reuses the kept configuration and data" {
  do_install
  before="$(secret core_db_password)"
  run "$OBSCTL" core remove
  run "$OBSCTL" core install --no-build --no-admin --no-timers
  [ "$status" -eq 0 ]
  [ "$(secret core_db_password)" = "$before" ]
}

@test "purge without a confirmation (non-interactive) is refused and deletes nothing" {
  do_install
  run "$OBSCTL" core remove --purge </dev/null
  [ "$status" -ne 0 ]
  [[ "$output" == *"PERMANENT DELETION"* ]]
  [[ "$output" == *"purge core"* ]]
  [[ "$(docker_log)" != *"--volumes"* ]]
  [ -f "${OBS_ETC}/core.env" ]
  [ -s "${OBS_ETC}/secrets/core_db_password" ]
}

@test "purge with the wrong confirmation text is refused" {
  do_install
  run "$OBSCTL" core remove --purge --confirm-purge "purge everything"
  [ "$status" -ne 0 ]
  [[ "$(docker_log)" != *"--volumes"* ]]
  [ -f "${OBS_ETC}/core.env" ]
}

@test "purge lists exactly what it will delete before asking" {
  do_install
  run "$OBSCTL" core remove --purge --confirm-purge "nope"
  [[ "$output" == *"obs-core-pgdata"* ]]
  [[ "$output" == *"obs-core-caddy-data"* ]]
  [[ "$output" == *"core_jwt_secret"* ]]
  [[ "$output" == *"KEPT"* ]]
}

@test "confirmed purge removes volumes, config and secrets but keeps backups and the backup passphrase" {
  do_install
  run "$OBSCTL" core backup --quiet
  run "$OBSCTL" core remove --purge --confirm-purge "purge core"
  [ "$status" -eq 0 ]
  [[ "$(docker_log)" == *"down --volumes --rmi local --remove-orphans"* ]]
  [ ! -e "${OBS_ETC}/core.env" ]
  [ ! -e "${OBS_ETC}/secrets/core_db_password" ]
  [ ! -e "${OBS_ETC}/core" ]
  [ -s "${OBS_ETC}/secrets/backup_passphrase" ]
  [ -n "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)" ]
}

@test "deleting backups needs its own second confirmation" {
  do_install
  run "$OBSCTL" core backup --quiet
  run "$OBSCTL" core remove --purge --include-backups --confirm-purge "purge core"
  [ "$status" -ne 0 ]
  [ -n "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg)" ]
  [ -f "${OBS_ETC}/core.env" ]
  run "$OBSCTL" core remove --purge --include-backups --confirm-purge "purge core" --confirm-delete-backups "delete core backups"
  [ "$status" -eq 0 ]
  [ -z "$(ls "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg 2>/dev/null)" ]
}

@test "upgrade takes a labelled backup, builds, migrates and starts" {
  do_install
  echo "9.9.9" > "${TMP}/VERSION.new"
  run "$OBSCTL" core upgrade
  [ "$status" -eq 0 ]
  ls "${OBS_BACKUP_DIR}"/obs-core_*pre-upgrade.tar.gpg
  log="$(docker_log)"
  [[ "$log" == *"build --pull"* ]]
  [[ "$log" == *"migrate"* ]]
}

@test "a failed upgrade build reverts the version setting and leaves services untouched" {
  do_install
  before="$(env_version)"
  FAKE_FAIL_BUILD=1 run "$OBSCTL" core upgrade
  [ "$status" -ne 0 ]
  [[ "$output" == *"version setting reverted"* ]]
  [ "$(env_version)" = "$before" ]
}

env_version() { grep '^OBS_VERSION=' "${OBS_ETC}/core.env"; }

@test "timers on installs and enables the systemd units with the real obsctl path" {
  do_install
  cat > "${TMP}/bin/systemctl" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "${TMP}/systemctl.log"
SH
  chmod +x "${TMP}/bin/systemctl"
  OBS_SKIP_SYSTEMD=0 run "$OBSCTL" core timers on
  [ "$status" -eq 0 ]
  grep -q "ExecStart=${OBSCTL} core watchdog --quiet" "${OBS_SYSTEMD_DIR}/obs-core-watchdog.service"
  grep -q "ExecStart=${OBSCTL} core backup --quiet" "${OBS_SYSTEMD_DIR}/obs-core-backup.service"
  grep -q "enable --now obs-core-watchdog.timer" "${TMP}/systemctl.log"
  grep -q "enable --now obs-core-backup.timer" "${TMP}/systemctl.log"
}

@test "export-ca refuses non-internal TLS modes and existing files" {
  do_install
  run "$OBSCTL" core export-ca "${TMP}/ca.crt"
  [ "$status" -eq 0 ]
  [ -s "${TMP}/ca.crt" ]
  run "$OBSCTL" core export-ca "${TMP}/ca.crt"
  [ "$status" -ne 0 ]
  [[ "$output" == *"already exists"* ]]
}

@test "backup-key refuses to print a secret to a non-terminal" {
  do_install
  run "$OBSCTL" core backup-key
  [ "$status" -ne 0 ]
  [[ "$output" == *"non-terminal"* ]]
}

@test "reconfigure keeps a copy of the previous Caddyfile and re-renders" {
  do_install
  run "$OBSCTL" core reconfigure --hostname new.test.local
  [ "$status" -eq 0 ]
  grep -q 'https://new.test.local {' "${OBS_ETC}/core/Caddyfile"
  ls "${OBS_ETC}"/core/Caddyfile.before-*
}

@test "all shell scripts pass shellcheck (skipped when shellcheck is absent)" {
  command -v shellcheck >/dev/null || skip "shellcheck not installed"
  run shellcheck -x -s bash "${REPO_ROOT}/bin/obsctl" "${REPO_ROOT}"/lib/*.sh "${REPO_ROOT}"/lib/modules/*.sh
  [ "$status" -eq 0 ]
}
