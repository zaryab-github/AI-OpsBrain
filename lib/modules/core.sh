#!/usr/bin/env bash
# core.sh - `obsctl core <verb>`: web UI, API, worker, PostgreSQL and the TLS proxy.
# Sourced by bin/obsctl after lib/common.sh and lib/docker.sh.
# shellcheck shell=bash
# shellcheck disable=SC2034  # MOD_* variables are read by lib/docker.sh

MOD_NAME="core"
MOD_PROJECT="obs-core"
MOD_DIR="${OBS_ROOT}/deploy/core"
MOD_COMPOSE_FILE="${MOD_DIR}/docker-compose.yml"
MOD_ENV_FILE="${OBS_ETC}/core.env"
MOD_CONF_DIR="${OBS_ETC}/core"
MOD_VOLUMES=(obs-core-pgdata obs-core-caddy-data obs-core-caddy-config)
MOD_SECRETS=(core_db_password core_jwt_secret core_field_key core_audit_hmac_key core_metrics_token)
MOD_SERVICES=(postgres api worker proxy)
MOD_TIMERS=(obs-core-watchdog obs-core-backup)

core_usage() {
  cat <<'EOF'
Usage: obsctl core <command> [options]

Lifecycle
  install        Install (or re-start after `remove`) the core module
  status         Show service, TLS, backup and timer status      [--json]
  upgrade        Back up, rebuild images, migrate the database, restart
  backup         Create an encrypted backup                      [--label L] [--keep N]
  restore FILE   Restore an encrypted backup (replaces the core database)
  remove         Stop and remove containers; KEEPS all data and config
  remove --purge Delete data too (asks you to type a confirmation)

Operations
  reconfigure    Change hostname / TLS settings
  logs [SERVICE] Show service logs                                [-f]
  watchdog       Run the health checks now                        [--quiet]
  admin ...      create | reset-password | unlock | disable-mfa
  verify-audit   Verify the audit-log hash chain
  export-ca FILE Export the internal CA certificate for client trust
  backup-key     Show the backup encryption passphrase
  timers on|off  Enable or disable the watchdog/backup timers

Run `obsctl core <command> --help` for options.
EOF
}

# core_backups_newest_first : prints core backup files, newest first (one per line)
core_backups_newest_first() {
  find "${OBS_BACKUP_DIR}" -maxdepth 1 -type f -name 'obs-core_*.tar.gpg' -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | cut -d' ' -f2-
}

core_installed() { [[ -f "$MOD_ENV_FILE" ]]; }

core_require_installed() {
  core_installed || die "core is not installed (no ${MOD_ENV_FILE}). Run: obsctl core install"
}

core_version() { tr -d '[:space:]' < "${OBS_ROOT}/VERSION"; }

core_url() {
  local host port url
  host="$(env_get "$MOD_ENV_FILE" OBS_HOSTNAME)"
  port="$(env_get "$MOD_ENV_FILE" OBS_HTTPS_PORT 443)"
  [[ "$host" == *:* ]] && host="[${host}]"
  url="https://${host}"
  [[ "$port" != "443" ]] && url="${url}:${port}"
  printf '%s/' "$url"
}

# ---------------------------------------------------------------- preflight
core_preflight() {
  local ok=0 cmd http_port="${1:-80}" https_port="${2:-443}" free_kb docker_root
  for cmd in openssl gpg curl tar sha256sum; do
    have_cmd "$cmd" || { log_err "missing required command: ${cmd}"; ok=1; }
  done
  if ! docker_ready; then
    log_err "docker with the compose plugin is not usable (is the daemon running and do you have access?)"
    ok=1
  fi
  if have_cmd ss; then
    local p
    for p in "$http_port" "$https_port"; do
      if ss -H -ltn "sport = :${p}" 2>/dev/null | grep -q .; then
        log_err "port ${p} is already in use on this host (choose others with --http-port / --https-port)"
        ok=1
      fi
    done
  fi
  docker_root="/var/lib/docker"
  [[ -d "$docker_root" ]] || docker_root="/"
  free_kb="$(df -Pk "$docker_root" 2>/dev/null | awk 'NR==2{print $4}')"
  if [[ -n "$free_kb" ]] && (( free_kb < ${OBS_MIN_FREE_KB:-5242880} )); then
    log_err "less than 5 GiB free under ${docker_root}"
    ok=1
  fi
  return "$ok"
}

# ---------------------------------------------------------------- config rendering
core_render_caddyfile() {
  local host="$1" tls_mode="$2" acme_email="$3" https_port="$4" out="$5"
  local tmpl global="" tls="" site="$host" redir=""
  tmpl="$(cat "${MOD_DIR}/Caddyfile.tmpl")"
  [[ "$host" == *:* ]] && site="[${host}]"
  global="default_sni ${host}"
  case "$tls_mode" in
    internal) tls="tls internal" ;;
    acme)
      tls=""
      [[ -n "$acme_email" ]] && global="${global}"$'\n\t'"email ${acme_email}"
      ;;
    custom) tls="tls /etc/caddy/certs/server.crt /etc/caddy/certs/server.key" ;;
    *) die "unknown TLS mode: ${tls_mode}" ;;
  esac
  [[ "$https_port" != "443" ]] && redir=":${https_port}"
  tmpl="${tmpl//@@GLOBAL@@/${global}}"
  tmpl="${tmpl//@@SITE@@/${site}}"
  tmpl="${tmpl//@@TLS@@/${tls}}"
  tmpl="${tmpl//@@REDIR_PORT@@/${redir}}"
  printf '%s\n' "$tmpl" > "$out"
  chmod 0644 "$out"
}

core_validate_caddyfile() {
  log_info "validating the generated Caddyfile"
  dc run --rm --no-deps -T --entrypoint caddy proxy validate --config /etc/caddy/Caddyfile >/dev/null \
    || die "the generated Caddyfile is invalid (${MOD_CONF_DIR}/Caddyfile); see: obsctl core logs proxy"
}

core_generate_secrets() {
  mkdir -p "$OBS_SECRETS_DIR"
  chmod 0750 "$OBS_SECRETS_DIR"
  [[ "${OBS_SKIP_CHOWN:-0}" == "1" ]] || chown "root:${OBS_CONTAINER_GID}" "$OBS_SECRETS_DIR"
  write_secret core_db_password "$(rand_b64url 32)"
  write_secret core_jwt_secret "$(rand_b64url 48)"
  write_secret core_field_key "$(rand_fernet_key)"
  write_secret core_audit_hmac_key "$(rand_b64url 48)"
  write_secret core_metrics_token "$(rand_b64url 32)"
  # Shared by every module's backups. Never regenerated once it exists.
  write_secret backup_passphrase "$(rand_b64url 48)"
}

core_write_env() {
  local host="$1" tls_mode="$2" http_port="$3" https_port="$4" keep="$5" timers="$6"
  mkdir -p "$OBS_ETC"
  touch "$MOD_ENV_FILE"
  chmod 0640 "$MOD_ENV_FILE"
  env_set "$MOD_ENV_FILE" OBS_VERSION "$(core_version)"
  env_set "$MOD_ENV_FILE" OBS_HOSTNAME "$host"
  env_set "$MOD_ENV_FILE" OBS_TLS_MODE "$tls_mode"
  env_set "$MOD_ENV_FILE" OBS_HTTP_PORT "$http_port"
  env_set "$MOD_ENV_FILE" OBS_HTTPS_PORT "$https_port"
  env_set "$MOD_ENV_FILE" OBS_ETC "$OBS_ETC"
  env_set "$MOD_ENV_FILE" OBS_SECRETS_DIR "$OBS_SECRETS_DIR"
  env_set "$MOD_ENV_FILE" OBS_CORE_CONF_DIR "$MOD_CONF_DIR"
  env_set "$MOD_ENV_FILE" OBS_BACKUP_KEEP "$keep"
  env_set "$MOD_ENV_FILE" OBS_BACKUP_TIMER "$timers"
}

# ---------------------------------------------------------------- systemd
core_timers_set() {
  local state="$1" unit src
  if ! systemd_usable; then
    log_warn "systemd not available: schedule 'obsctl core watchdog' and 'obsctl core backup' with cron instead"
    return 0
  fi
  case "$state" in
    on)
      for unit in "${MOD_TIMERS[@]}"; do
        for src in service timer; do
          sed "s|@OBSCTL@|${OBS_CTL}|g" "${MOD_DIR}/systemd/${unit}.${src}" > "${OBS_SYSTEMD_DIR}/${unit}.${src}"
          chmod 0644 "${OBS_SYSTEMD_DIR}/${unit}.${src}"
        done
      done
      systemctl daemon-reload
      systemctl enable --now obs-core-watchdog.timer
      if [[ "$(env_get "$MOD_ENV_FILE" OBS_BACKUP_TIMER on)" == "on" ]]; then
        systemctl enable --now obs-core-backup.timer
      fi
      ;;
    off)
      for unit in "${MOD_TIMERS[@]}"; do
        systemctl disable --now "${unit}.timer" >/dev/null 2>&1 || true
        rm -f "${OBS_SYSTEMD_DIR}/${unit}.service" "${OBS_SYSTEMD_DIR}/${unit}.timer"
      done
      systemctl daemon-reload
      ;;
  esac
}

core_timers_active() {
  if ! systemd_usable; then printf 'n/a'; return 0; fi
  systemctl is-active "$1.timer" 2>/dev/null || true
}

# ---------------------------------------------------------------- app CLI helper
# core_cli_stdin <args...> : run `python -m app.cli ...` in the api image; stdin is passed through
core_cli_stdin() {
  if state_is_good "$(container_state api)"; then
    dc exec -T api python -m app.cli "$@"
  else
    dc run --rm --no-deps -T api python -m app.cli "$@"
  fi
}

# core_cli <args...> : same, but never reads (or swallows) the caller's stdin
core_cli() { core_cli_stdin "$@" </dev/null; }

core_migrate() {
  log_info "applying database migrations"
  dc up -d postgres
  wait_healthy 120 postgres || die "postgres did not become healthy; see: obsctl core logs postgres"
  dc run --rm --no-deps -T migrate || die "database migration failed; see: obsctl core logs migrate"
}

# ---------------------------------------------------------------- install
core_install() {
  local host="" tls_mode="internal" acme_email="" cert="" key="" http_port=80 https_port=443
  local admin_user="" admin_generate=0 admin_stdin=0 no_admin=0 timers=on keep="" no_build=0
  while (( $# )); do
    case "$1" in
      --hostname) host="$2"; shift 2 ;;
      --tls) tls_mode="$2"; shift 2 ;;
      --acme-email) acme_email="$2"; shift 2 ;;
      --cert) cert="$2"; shift 2 ;;
      --key) key="$2"; shift 2 ;;
      --http-port) http_port="$2"; shift 2 ;;
      --https-port) https_port="$2"; shift 2 ;;
      --admin-user) admin_user="$2"; shift 2 ;;
      --admin-generate-password) admin_generate=1; shift ;;
      --admin-password-stdin) admin_stdin=1; shift ;;
      --no-admin) no_admin=1; shift ;;
      --no-timers) timers=off; shift ;;
      --backup-keep) keep="$2"; shift 2 ;;
      --no-build) no_build=1; shift ;;
      -y|--yes) export OBS_ASSUME_YES=1; shift ;;
      -h|--help) core_install_help; return 0 ;;
      *) die "unknown option for install: $1 (see: obsctl core install --help)" ;;
    esac
  done
  require_root core install

  local resume=0
  if core_installed; then
    resume=1
    log_info "found an existing core configuration; reusing it (use 'obsctl core reconfigure' to change settings)"
    host="$(env_get "$MOD_ENV_FILE" OBS_HOSTNAME)"
    tls_mode="$(env_get "$MOD_ENV_FILE" OBS_TLS_MODE internal)"
    http_port="$(env_get "$MOD_ENV_FILE" OBS_HTTP_PORT 80)"
    https_port="$(env_get "$MOD_ENV_FILE" OBS_HTTPS_PORT 443)"
    keep="$(env_get "$MOD_ENV_FILE" OBS_BACKUP_KEEP 0)"
    timers="$(env_get "$MOD_ENV_FILE" OBS_BACKUP_TIMER on)"
  else
    [[ -n "$host" ]] || host="$(prompt_default "Hostname or IP address users will open in the browser" "")"
    valid_hostname "$host" || die "a valid --hostname is required (DNS name or IP address)"
    case "$tls_mode" in internal|acme|custom) ;; *) die "--tls must be internal, acme or custom" ;; esac
    valid_port "$http_port" || die "invalid --http-port"
    valid_port "$https_port" || die "invalid --https-port"
    if [[ "$tls_mode" == "custom" ]]; then
      [[ -r "$cert" && -r "$key" ]] || die "--tls custom needs readable --cert and --key files"
    fi
    if [[ "$tls_mode" == "acme" ]]; then
      [[ "$host" == *.* && ! "$host" =~ ^[0-9.]+$ ]] || die "--tls acme needs a public DNS name, not an IP address"
      [[ "$https_port" == "443" && "$http_port" == "80" ]] || die "--tls acme needs ports 80 and 443"
    fi
    if [[ -z "$keep" ]]; then
      keep="$(prompt_default "How many backups to keep (0 = keep all, nothing is ever pruned)" "14")"
    fi
    [[ "$keep" =~ ^[0-9]+$ ]] || die "--backup-keep must be a number"
    core_preflight "$http_port" "$https_port" || die "preflight checks failed; fix the problems above and re-run"
  fi

  if (( ! resume )); then
    log_info "creating configuration in ${OBS_ETC}"
    mkdir -p "${MOD_CONF_DIR}/certs" "$OBS_BACKUP_DIR"
    chmod 0700 "$OBS_BACKUP_DIR"
    if [[ "$tls_mode" == "custom" ]]; then
      install -m 0644 "$cert" "${MOD_CONF_DIR}/certs/server.crt"
      install -m 0600 "$key" "${MOD_CONF_DIR}/certs/server.key"
    fi
    core_generate_secrets
    core_write_env "$host" "$tls_mode" "$http_port" "$https_port" "$keep" "$timers"
    core_render_caddyfile "$host" "$tls_mode" "$acme_email" "$https_port" "${MOD_CONF_DIR}/Caddyfile"
  else
    docker_ready || die "docker with the compose plugin is not usable"
    mkdir -p "${MOD_CONF_DIR}/certs" "$OBS_BACKUP_DIR"
    core_generate_secrets   # only creates secrets that are missing
    env_set "$MOD_ENV_FILE" OBS_VERSION "$(core_version)"
  fi

  if (( ! no_build )); then
    log_info "building images (this takes a few minutes the first time)"
    dc build --pull || die "image build failed"
  fi
  core_validate_caddyfile
  core_migrate
  log_info "starting services"
  dc up -d
  wait_healthy 240 "${MOD_SERVICES[@]}" || die "services did not become healthy; run: obsctl core status ; obsctl core logs"

  if (( ! no_admin )); then
    core_bootstrap_admin "$admin_user" "$admin_generate" "$admin_stdin"
  fi
  core_timers_set on
  core_print_summary
}

core_install_help() {
  cat <<'EOF'
Usage: obsctl core install [options]

  --hostname H            DNS name or IP users open in the browser (asked if omitted)
  --tls MODE              internal (default, own CA) | acme (Let's Encrypt) | custom
  --acme-email E          contact e-mail for --tls acme
  --cert F --key F        certificate and key files for --tls custom
  --http-port N           host port for the HTTP->HTTPS redirect (default 80)
  --https-port N          host port for the web UI (default 443)
  --admin-user U          first administrator (asked if omitted)
  --admin-generate-password   generate the first password and print it once
  --admin-password-stdin  read the first password from stdin
  --no-admin              do not create an administrator (use before `restore`)
  --no-timers             do not install the watchdog/backup systemd timers
  --backup-keep N         keep N backups; 0 keeps everything (nothing is ever pruned)
  --no-build              reuse already built images
  -y, --yes               answer yes to harmless prompts

Re-running install on an already installed or removed module reuses its config and data.
EOF
}

core_bootstrap_admin() {
  local user="$1" generate="$2" from_stdin="$3" pw
  if core_cli has-users >/dev/null 2>&1; then
    log_info "users already exist; not creating an administrator"
    return 0
  fi
  if [[ -z "$user" ]]; then user="$(prompt_default "Administrator username" "")"; fi
  valid_username "$user" || die "administrator username must be 3-32 chars: lowercase letters, digits, . _ - and start with a letter"
  if (( generate )); then
    log_info "creating administrator '${user}' with a generated one-time password"
    core_cli create-admin --username "$user" --generate
  elif (( from_stdin )); then
    core_cli_stdin create-admin --username "$user" --password-stdin
  else
    pw="$(prompt_secret_twice "Administrator password (min 12 characters)")"
    printf '%s' "$pw" | core_cli_stdin create-admin --username "$user" --password-stdin
  fi
}

core_print_summary() {
  local url keep
  url="$(core_url)"
  keep="$(env_get "$MOD_ENV_FILE" OBS_BACKUP_KEEP 0)"
  cat <<EOF

${C_GRN}Core module is running.${C_OFF}

  Web UI:        ${url}
  TLS mode:      $(env_get "$MOD_ENV_FILE" OBS_TLS_MODE)
  Status:        obsctl core status
  Backups:       ${OBS_BACKUP_DIR}  (encrypted; keep setting: ${keep}, 0 = keep all)

IMPORTANT - do these now:
  1. Copy the backup passphrase to a safe place OFF this server:
         obsctl core backup-key
     Without it, backups cannot be restored on a new server.
EOF
  if [[ "$(env_get "$MOD_ENV_FILE" OBS_TLS_MODE)" == "internal" ]]; then
    cat <<EOF
  2. Your browser will warn about the certificate until you trust the internal CA:
         obsctl core export-ca ./obs-root-ca.crt
     Import that file into the operating system / browser trust store of every client.
EOF
  fi
  echo
}

# ---------------------------------------------------------------- reconfigure
core_reconfigure() {
  local host tls_mode acme_email="" cert="" key="" https_port http_port new_host="" new_tls="" new_https="" new_http=""
  core_require_installed
  while (( $# )); do
    case "$1" in
      --hostname) new_host="$2"; shift 2 ;;
      --tls) new_tls="$2"; shift 2 ;;
      --acme-email) acme_email="$2"; shift 2 ;;
      --cert) cert="$2"; shift 2 ;;
      --key) key="$2"; shift 2 ;;
      --http-port) new_http="$2"; shift 2 ;;
      --https-port) new_https="$2"; shift 2 ;;
      -h|--help) echo "Usage: obsctl core reconfigure [--hostname H] [--tls internal|acme|custom] [--acme-email E] [--cert F --key F] [--http-port N] [--https-port N]"; return 0 ;;
      *) die "unknown option for reconfigure: $1" ;;
    esac
  done
  require_root core reconfigure
  host="${new_host:-$(env_get "$MOD_ENV_FILE" OBS_HOSTNAME)}"
  tls_mode="${new_tls:-$(env_get "$MOD_ENV_FILE" OBS_TLS_MODE internal)}"
  http_port="${new_http:-$(env_get "$MOD_ENV_FILE" OBS_HTTP_PORT 80)}"
  https_port="${new_https:-$(env_get "$MOD_ENV_FILE" OBS_HTTPS_PORT 443)}"
  valid_hostname "$host" || die "invalid hostname"
  case "$tls_mode" in internal|acme|custom) ;; *) die "--tls must be internal, acme or custom" ;; esac
  valid_port "$http_port" || die "invalid http port"
  valid_port "$https_port" || die "invalid https port"
  if [[ "$tls_mode" == "custom" && -n "$cert$key" ]]; then
    [[ -r "$cert" && -r "$key" ]] || die "--cert and --key must both be readable files"
    install -m 0644 "$cert" "${MOD_CONF_DIR}/certs/server.crt"
    install -m 0600 "$key" "${MOD_CONF_DIR}/certs/server.key"
  fi
  if [[ "$tls_mode" == "custom" && ! -r "${MOD_CONF_DIR}/certs/server.crt" ]]; then
    die "--tls custom needs --cert and --key"
  fi
  local backup_conf
  backup_conf="${MOD_CONF_DIR}/Caddyfile.before-$(ts_utc)"
  cp -p "${MOD_CONF_DIR}/Caddyfile" "$backup_conf"
  env_set "$MOD_ENV_FILE" OBS_HOSTNAME "$host"
  env_set "$MOD_ENV_FILE" OBS_TLS_MODE "$tls_mode"
  env_set "$MOD_ENV_FILE" OBS_HTTP_PORT "$http_port"
  env_set "$MOD_ENV_FILE" OBS_HTTPS_PORT "$https_port"
  core_render_caddyfile "$host" "$tls_mode" "$acme_email" "$https_port" "${MOD_CONF_DIR}/Caddyfile"
  if ! core_validate_caddyfile; then
    cp -p "$backup_conf" "${MOD_CONF_DIR}/Caddyfile"
    die "new configuration rejected; the previous Caddyfile was restored"
  fi
  dc up -d --force-recreate proxy
  wait_healthy 120 proxy || die "proxy did not become healthy; previous Caddyfile saved as ${backup_conf}"
  log_info "reconfigured. New URL: $(core_url)"
}

# ---------------------------------------------------------------- status / watchdog
core_status() {
  local json=0 svc state ok=1 last="" age_h="n/a" tls
  while (( $# )); do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help) echo "Usage: obsctl core status [--json]"; return 0 ;;
      *) die "unknown option for status: $1" ;;
    esac
  done
  if ! core_installed; then
    if (( json )); then printf '{"module":"core","installed":false}\n'; else echo "core: not installed"; fi
    return 3
  fi
  docker_ready || die "docker is not usable"
  local -A states=()
  for svc in "${MOD_SERVICES[@]}"; do
    state="$(container_state "$svc")"
    states[$svc]="$state"
    state_is_good "$state" || ok=0
  done
  last="$(core_backups_newest_first | head -n 1 || true)"
  if [[ -n "$last" ]]; then age_h=$(( ( $(date +%s) - $(stat -c %Y "$last") ) / 3600 )); fi
  tls="$(env_get "$MOD_ENV_FILE" OBS_TLS_MODE)"
  if (( json )); then
    printf '{"module":"core","installed":true,"version":"%s","url":"%s","tls_mode":"%s","healthy":%s,"services":{' \
      "$(env_get "$MOD_ENV_FILE" OBS_VERSION)" "$(core_url)" "$tls" "$([[ $ok == 1 ]] && echo true || echo false)"
    local first=1
    for svc in "${MOD_SERVICES[@]}"; do
      (( first )) || printf ','
      first=0
      printf '"%s":"%s"' "$svc" "${states[$svc]}"
    done
    printf '},"last_backup":"%s","last_backup_age_hours":"%s"}\n' "${last##*/}" "$age_h"
  else
    printf 'Module:        core (version %s)\n' "$(env_get "$MOD_ENV_FILE" OBS_VERSION)"
    printf 'URL:           %s\n' "$(core_url)"
    printf 'TLS mode:      %s\n' "$tls"
    printf 'Services:\n'
    for svc in "${MOD_SERVICES[@]}"; do printf '  %-10s %s\n' "$svc" "${states[$svc]}"; done
    printf 'Timers:        watchdog=%s backup=%s\n' "$(core_timers_active obs-core-watchdog)" "$(core_timers_active obs-core-backup)"
    if [[ -n "$last" ]]; then
      printf 'Last backup:   %s (%s hours ago)\n' "${last##*/}" "$age_h"
    else
      printf 'Last backup:   none yet (run: obsctl core backup)\n'
    fi
    if (( ok )); then echo "Overall:       healthy"; else echo "Overall:       DEGRADED - see: obsctl core logs"; fi
  fi
  (( ok )) && return 0 || return 1
}

# severity helpers for the watchdog: 0 ok, 1 warn, 2 crit
WD_ROWS=()
WD_WORST=0
wd_add() { # name severity detail
  local name="$1" sev="$2" detail="$3" label
  case "$sev" in 0) label=ok ;; 1) label=warn ;; *) label=crit ;; esac
  WD_ROWS+=("${name}"$'\t'"${label}"$'\t'"${detail}")
  (( sev > WD_WORST )) && WD_WORST="$sev"
  return 0
}

core_watchdog() {
  local quiet=0 svc state host port code pct root cert_end days_left sev row last age_h tls_mode name label detail dir
  while (( $# )); do
    case "$1" in
      --quiet) quiet=1; shift ;;
      -h|--help) echo "Usage: obsctl core watchdog [--quiet]   (exit 0 ok, 1 warning, 2 critical)"; return 0 ;;
      *) die "unknown option for watchdog: $1" ;;
    esac
  done
  core_require_installed
  WD_ROWS=(); WD_WORST=0
  host="$(env_get "$MOD_ENV_FILE" OBS_HOSTNAME)"
  port="$(env_get "$MOD_ENV_FILE" OBS_HTTPS_PORT 443)"
  tls_mode="$(env_get "$MOD_ENV_FILE" OBS_TLS_MODE internal)"

  for svc in "${MOD_SERVICES[@]}"; do
    state="$(container_state "$svc")"
    if state_is_good "$state"; then wd_add "container.${svc}" 0 "$state"; else wd_add "container.${svc}" 2 "$state"; fi
  done

  code="$(curl -ksS -m 10 -o /dev/null -w '%{http_code}' --resolve "${host}:${port}:127.0.0.1" \
    "https://${host}:${port}/api/v1/system/health" 2>/dev/null || true)"
  if [[ "$code" == "200" ]]; then wd_add "https.probe" 0 "GET /api/v1/system/health -> 200"
  else wd_add "https.probe" 2 "GET /api/v1/system/health -> ${code:-no response}"; fi

  cert_end="$(printf '' | openssl s_client -connect "127.0.0.1:${port}" -servername "$host" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | sed 's/^notAfter=//' || true)"
  if [[ -n "$cert_end" ]]; then
    days_left=$(( ( $(date -d "$cert_end" +%s) - $(date +%s) ) / 86400 ))
    if (( days_left < 0 )); then sev=2
    elif [[ "$tls_mode" == "internal" ]]; then sev=0   # short-lived certs renewed automatically
    elif (( days_left < 3 )); then sev=2
    elif (( days_left < 14 )); then sev=1
    else sev=0; fi
    wd_add "tls.certificate" "$sev" "expires ${cert_end} (${days_left} days)"
  else
    wd_add "tls.certificate" 1 "could not read the served certificate"
  fi

  root="$("${OBS_DOCKER}" info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
  for dir in "$root" "$OBS_BACKUP_DIR"; do
    [[ -d "$dir" ]] || continue
    pct="$(df -Pk "$dir" | awk 'NR==2{gsub("%","",$5); print $5}')"
    if (( pct >= 90 )); then sev=2; elif (( pct >= 80 )); then sev=1; else sev=0; fi
    wd_add "disk.${dir}" "$sev" "${pct}% used"
  done

  last="$(core_backups_newest_first | head -n 1 || true)"
  if [[ "$(env_get "$MOD_ENV_FILE" OBS_BACKUP_TIMER on)" != "on" && -z "$last" ]]; then
    wd_add "backup.recent" 1 "no backups exist and the backup timer is off"
  elif [[ -z "$last" ]]; then
    wd_add "backup.recent" 1 "no backup has completed yet"
  else
    age_h=$(( ( $(date +%s) - $(stat -c %Y "$last") ) / 3600 ))
    if (( age_h > 72 )); then sev=2; elif (( age_h > 36 )); then sev=1; else sev=0; fi
    wd_add "backup.recent" "$sev" "latest ${last##*/} is ${age_h}h old"
  fi

  if (( ! quiet )); then
    for row in "${WD_ROWS[@]}"; do
      IFS=$'\t' read -r name label detail <<<"$row"
      printf '%-28s %-5s %s\n' "$name" "$label" "$detail"
    done
  fi
  for row in "${WD_ROWS[@]}"; do
    IFS=$'\t' read -r name label detail <<<"$row"
    [[ "$label" == "ok" ]] || logger -t obsctl-core -p "daemon.$([[ $label == crit ]] && echo err || echo warning)" "${name}: ${label}: ${detail}" 2>/dev/null || true
  done
  # Report to the application so the UI shows host-level checks; never fail the watchdog over this.
  if state_is_good "$(container_state api)"; then
    printf '%s\n' "${WD_ROWS[@]}" | dc exec -T api python -m app.cli selfmon-report --source watchdog >/dev/null 2>&1 \
      || log_warn "could not report watchdog results to the application"
  fi
  return "$WD_WORST"
}

# ---------------------------------------------------------------- logs, admin, audit, CA, key
core_logs() {
  local follow=() svc=()
  while (( $# )); do
    case "$1" in
      -f|--follow) follow=(-f); shift ;;
      -h|--help) echo "Usage: obsctl core logs [-f] [postgres|migrate|api|worker|proxy]"; return 0 ;;
      *) svc+=("$1"); shift ;;
    esac
  done
  core_require_installed
  dc logs --tail=200 "${follow[@]}" "${svc[@]}"
}

core_admin() {
  local action="${1:-}"; shift || true
  core_require_installed
  case "$action" in
    create)
      local user="" generate=0
      while (( $# )); do
        case "$1" in
          --user) user="$2"; shift 2 ;;
          --generate-password) generate=1; shift ;;
          *) die "unknown option: $1" ;;
        esac
      done
      valid_username "$user" || die "--user is required (lowercase letters, digits, . _ -)"
      if (( generate )); then core_cli create-admin --username "$user" --generate
      elif [[ -t 0 ]]; then
        local pw; pw="$(prompt_secret_twice "Password (min 12 characters)")"
        printf '%s' "$pw" | core_cli_stdin create-admin --username "$user" --password-stdin
      else core_cli_stdin create-admin --username "$user" --password-stdin; fi
      ;;
    reset-password)
      local user="" generate=0
      while (( $# )); do
        case "$1" in
          --user) user="$2"; shift 2 ;;
          --generate-password) generate=1; shift ;;
          *) die "unknown option: $1" ;;
        esac
      done
      [[ -n "$user" ]] || die "--user is required"
      if (( generate )); then core_cli reset-password --username "$user" --generate
      elif [[ -t 0 ]]; then
        local pw; pw="$(prompt_secret_twice "New password (min 12 characters)")"
        printf '%s' "$pw" | core_cli_stdin reset-password --username "$user" --password-stdin
      else core_cli_stdin reset-password --username "$user" --password-stdin; fi
      ;;
    unlock) [[ "${1:-}" == "--user" && -n "${2:-}" ]] || die "usage: obsctl core admin unlock --user NAME"; core_cli unlock --username "$2" ;;
    disable-mfa) [[ "${1:-}" == "--user" && -n "${2:-}" ]] || die "usage: obsctl core admin disable-mfa --user NAME"; core_cli disable-mfa --username "$2" ;;
    *) die "usage: obsctl core admin create|reset-password|unlock|disable-mfa --user NAME" ;;
  esac
}

core_verify_audit() { core_require_installed; core_cli verify-audit; }

core_export_ca() {
  local out="${1:-}"
  core_require_installed
  [[ -n "$out" ]] || die "usage: obsctl core export-ca FILE"
  [[ "$(env_get "$MOD_ENV_FILE" OBS_TLS_MODE)" == "internal" ]] || die "export-ca only applies to --tls internal"
  [[ ! -e "$out" ]] || die "${out} already exists; choose another name"
  dc cp proxy:/data/caddy/pki/authorities/local/root.crt "$out" \
    || die "could not read the CA from the proxy container (has it started at least once?)"
  chmod 0644 "$out"
  log_info "wrote ${out}"
  openssl x509 -in "$out" -noout -subject -fingerprint -sha256 || true
  echo "Import this certificate as a trusted root CA on every client that opens the UI."
}

core_backup_key() {
  require_root core backup-key
  [[ -r "${OBS_SECRETS_DIR}/backup_passphrase" ]] || die "no backup passphrase exists yet"
  if ! is_tty; then die "refusing to print a secret to a non-terminal"; fi
  printf 'This prints the passphrase that encrypts every backup. Store it in your password manager.\n' >&2
  confirm_yes "Show it now?" || die "aborted"
  cat "${OBS_SECRETS_DIR}/backup_passphrase"; printf '\n'
}

core_timers() {
  core_require_installed
  require_root core timers
  case "${1:-}" in
    on) env_set "$MOD_ENV_FILE" OBS_BACKUP_TIMER on; core_timers_set on ;;
    off)
      env_set "$MOD_ENV_FILE" OBS_BACKUP_TIMER off
      core_timers_set off
      log_warn "scheduled backups and the watchdog are now disabled"
      ;;
    *) die "usage: obsctl core timers on|off" ;;
  esac
}

# ---------------------------------------------------------------- backup / restore
# core_gpg_encrypt <in> <out> / core_gpg_decrypt <in> <out> [passphrase-file]
core_gpg() {
  local mode="$1" in="$2" out="$3" pass="${4:-${OBS_SECRETS_DIR}/backup_passphrase}" gh
  gh="$(mktemp -d)"; chmod 700 "$gh"
  if [[ "$mode" == "enc" ]]; then
    GNUPGHOME="$gh" gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$pass" \
      --symmetric --cipher-algo AES256 --compress-algo none -o "$out" "$in"
  else
    GNUPGHOME="$gh" gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$pass" \
      --decrypt -o "$out" "$in"
  fi
  local rc=$?
  rm -rf "$gh"
  return "$rc"
}

core_backup() {
  local label="" keep="" quiet=0 work stamp name out schema
  while (( $# )); do
    case "$1" in
      --label) label="$2"; shift 2 ;;
      --keep) keep="$2"; shift 2 ;;
      --quiet) quiet=1; shift ;;
      -h|--help) echo "Usage: obsctl core backup [--label L] [--keep N] [--quiet]"; return 0 ;;
      *) die "unknown option for backup: $1" ;;
    esac
  done
  core_require_installed
  require_root core backup
  docker_ready || die "docker is not usable"
  [[ -r "${OBS_SECRETS_DIR}/backup_passphrase" ]] || die "backup passphrase missing: ${OBS_SECRETS_DIR}/backup_passphrase"
  state_is_good "$(container_state postgres)" || die "postgres is not running/healthy; cannot back up"
  [[ -z "$keep" ]] && keep="$(env_get "$MOD_ENV_FILE" OBS_BACKUP_KEEP 0)"
  [[ "$keep" =~ ^[0-9]+$ ]] || die "--keep must be a number"
  [[ -z "$label" || "$label" =~ ^[a-z0-9-]{1,24}$ ]] || die "--label must be lowercase letters, digits and dashes"

  mkdir -p "$OBS_BACKUP_DIR"; chmod 0700 "$OBS_BACKUP_DIR"
  stamp="$(ts_utc)"
  name="obs-core_${stamp}_v$(env_get "$MOD_ENV_FILE" OBS_VERSION)${label:+_${label}}"
  work="$(mktemp -d "${OBS_BACKUP_DIR}/.work.XXXXXX")"
  register_tmp "$work"
  chmod 0700 "$work"
  mkdir -p "${work}/${name}/config/secrets" "${work}/${name}/config/certs"
  local root="${work}/${name}"

  (( quiet )) || log_info "dumping the database"
  dc exec -T postgres pg_dump -U obs -d obs -Fc --no-owner > "${root}/db.dump" || die "pg_dump failed"
  [[ -s "${root}/db.dump" ]] || die "pg_dump produced an empty file"

  (( quiet )) || log_info "saving the TLS state and configuration"
  dc exec -T proxy tar -C /data -cf - . > "${root}/caddy-data.tar" || die "could not archive the proxy data volume"
  cp -p "$MOD_ENV_FILE" "${root}/config/core.env"
  cp -p "${MOD_CONF_DIR}/Caddyfile" "${root}/config/Caddyfile"
  cp -p "${MOD_CONF_DIR}"/certs/* "${root}/config/certs/" 2>/dev/null || true
  local s
  for s in "${MOD_SECRETS[@]}"; do
    [[ "$s" == "core_db_password" ]] && continue   # tied to the local database cluster, not portable
    cp -p "${OBS_SECRETS_DIR}/${s}" "${root}/config/secrets/${s}"
  done

  schema="$(dc exec -T postgres psql -U obs -d obs -Atc 'select version_num from alembic_version' 2>/dev/null | tr -d '\r' || true)"
  {
    printf 'module=core\nversion=%s\ncreated_utc=%s\nhostname=%s\nschema_revision=%s\nlabel=%s\n' \
      "$(env_get "$MOD_ENV_FILE" OBS_VERSION)" "$stamp" "$(env_get "$MOD_ENV_FILE" OBS_HOSTNAME)" "${schema:-unknown}" "$label"
  } > "${root}/MANIFEST"
  ( cd "$root" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > "${work}/SHA256SUMS.tmp" && mv "${work}/SHA256SUMS.tmp" SHA256SUMS )

  tar -C "$work" -cf "${work}/${name}.tar" "$name"
  out="${OBS_BACKUP_DIR}/${name}.tar.gpg"
  core_gpg enc "${work}/${name}.tar" "$out" || die "encryption failed"
  chmod 0600 "$out"

  # Verify: it must decrypt and list.
  core_gpg dec "$out" "${work}/verify.tar" || die "VERIFY FAILED: cannot decrypt the new backup"
  tar -tf "${work}/verify.tar" >/dev/null || die "VERIFY FAILED: archive is unreadable"
  ( cd "${OBS_BACKUP_DIR}" && sha256sum "${name}.tar.gpg" > "${name}.tar.gpg.sha256" )
  chmod 0600 "${out}.sha256"

  if (( quiet )); then logger -t obsctl-core "backup written: ${out}" 2>/dev/null || true
  else log_info "backup written and verified: ${out} ($(human_bytes "$(stat -c %s "$out")"))"; fi

  if (( keep > 0 )); then
    local old
    old="$(core_backups_newest_first | tail -n "+$((keep + 1))" || true)"
    if [[ -n "$old" ]]; then
      (( quiet )) || log_info "pruning backups beyond the newest ${keep} (policy set at install, 0 disables)"
      while IFS= read -r f; do rm -f -- "$f" "${f}.sha256"; done <<<"$old"
    fi
  fi
}

core_restore() {
  local file="" confirm="" pass="${OBS_SECRETS_DIR}/backup_passphrase" work stamp
  while (( $# )); do
    case "$1" in
      --confirm-restore) confirm="$2"; shift 2 ;;
      --passphrase-file) pass="$2"; shift 2 ;;
      -h|--help)
        echo "Usage: obsctl core restore FILE [--passphrase-file F] [--confirm-restore 'restore core']"
        return 0 ;;
      -*) die "unknown option for restore: $1" ;;
      *) file="$1"; shift ;;
    esac
  done
  [[ -n "$file" && -r "$file" ]] || die "usage: obsctl core restore FILE (file must exist)"
  [[ -r "$pass" ]] || die "passphrase file not readable: ${pass} (use --passphrase-file)"
  core_require_installed
  require_root core restore
  docker_ready || die "docker is not usable"
  state_is_good "$(container_state postgres)" || {
    log_info "starting postgres"
    dc up -d postgres
    wait_healthy 120 postgres || die "postgres did not become healthy"
  }

  mkdir -p "$OBS_BACKUP_DIR"
  work="$(mktemp -d "${OBS_BACKUP_DIR}/.restore.XXXXXX")"; chmod 0700 "$work"
  register_tmp "$work"
  [[ ! -r "${file}.sha256" ]] || ( cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256" >/dev/null ) \
    || die "checksum mismatch: the backup file is damaged"
  log_info "decrypting and verifying the backup"
  core_gpg dec "$file" "${work}/b.tar" "$pass" || die "cannot decrypt (wrong passphrase or damaged file)"
  tar -C "$work" -xf "${work}/b.tar"
  local root
  root="$(find "$work" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -f "${root}/MANIFEST" && -f "${root}/db.dump" ]] || die "not a core backup (MANIFEST or db.dump missing)"
  ( cd "$root" && sha256sum -c SHA256SUMS >/dev/null ) || die "backup content failed its checksum verification"
  grep -q '^module=core$' "${root}/MANIFEST" || die "this backup is not for the core module"
  local b_version b_schema b_created
  b_version="$(env_get "${root}/MANIFEST" version)"
  b_schema="$(env_get "${root}/MANIFEST" schema_revision)"
  b_created="$(env_get "${root}/MANIFEST" created_utc)"

  confirm_typed "restore core" "$confirm" \
"This REPLACES the core database (users, roles, audit log, settings) and configuration with:
  backup created:  ${b_created}
  backup version:  ${b_version} (schema ${b_schema})
  installed:       $(env_get "$MOD_ENV_FILE" OBS_VERSION)
A safety backup of the current state is taken first (label 'pre-restore')."

  if state_is_good "$(container_state postgres)"; then
    log_info "taking a safety backup of the current state"
    core_backup --label pre-restore --quiet || die "safety backup failed; nothing was changed"
  fi
  stamp="$(ts_utc)"
  log_info "stopping api, worker and proxy"
  dc stop api worker proxy >/dev/null 2>&1 || true

  log_info "restoring the database"
  dc exec -T postgres psql -U obs -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS obs WITH (FORCE)" -c "CREATE DATABASE obs OWNER obs" >/dev/null \
    || die "could not recreate the database"
  dc exec -T postgres pg_restore -U obs -d obs --no-owner --exit-on-error < "${root}/db.dump" \
    || die "pg_restore failed. Your pre-restore safety backup is in ${OBS_BACKUP_DIR}"

  log_info "restoring configuration and secrets (previous copies kept in ${OBS_ETC}/pre-restore-${stamp})"
  mkdir -p "${OBS_ETC}/pre-restore-${stamp}"
  cp -a "$MOD_ENV_FILE" "${MOD_CONF_DIR}" "${OBS_SECRETS_DIR}" "${OBS_ETC}/pre-restore-${stamp}/" 2>/dev/null || true
  local f name
  for f in "${root}"/config/secrets/*; do
    [[ -e "$f" ]] || continue
    name="$(basename "$f")"
    write_secret "$name" "$(cat "$f")" force
  done
  install -m 0644 "${root}/config/Caddyfile" "${MOD_CONF_DIR}/Caddyfile"
  if compgen -G "${root}/config/certs/*" >/dev/null; then
    cp -p "${root}"/config/certs/* "${MOD_CONF_DIR}/certs/"
  fi
  # keep the local ports/paths, restore hostname + TLS mode
  env_set "$MOD_ENV_FILE" OBS_HOSTNAME "$(env_get "${root}/config/core.env" OBS_HOSTNAME)"
  env_set "$MOD_ENV_FILE" OBS_TLS_MODE "$(env_get "${root}/config/core.env" OBS_TLS_MODE internal)"

  log_info "restoring the TLS state (internal CA)"
  dc run --rm --no-deps -T --entrypoint sh proxy -c 'rm -rf /data/* /data/.[!.]* 2>/dev/null; tar -C /data -xf -' \
    < "${root}/caddy-data.tar" || log_warn "could not restore proxy TLS state; a new internal CA will be generated"

  core_migrate
  dc up -d
  wait_healthy 240 "${MOD_SERVICES[@]}" || die "services did not become healthy after restore; run: obsctl core logs"
  log_info "verifying the audit chain"
  core_cli verify-audit || log_warn "audit chain verification reported a problem; see the output above"
  log_info "restore complete. URL: $(core_url)"
}

# ---------------------------------------------------------------- upgrade
core_upgrade() {
  local no_backup=0 new old pre
  while (( $# )); do
    case "$1" in
      --no-backup) no_backup=1; shift ;;
      -h|--help) echo "Usage: obsctl core upgrade [--no-backup]"; return 0 ;;
      *) die "unknown option for upgrade: $1" ;;
    esac
  done
  core_require_installed
  require_root core upgrade
  docker_ready || die "docker is not usable"
  new="$(core_version)"
  old="$(env_get "$MOD_ENV_FILE" OBS_VERSION)"
  log_info "upgrading core ${old} -> ${new}"
  if (( no_backup )); then
    log_warn "skipping the pre-upgrade backup (--no-backup)"
  else
    core_backup --label pre-upgrade || die "pre-upgrade backup failed; nothing was changed"
    pre="$(core_backups_newest_first | grep -- '_pre-upgrade\.tar\.gpg$' | head -n 1 || true)"
  fi
  env_set "$MOD_ENV_FILE" OBS_VERSION "$new"
  dc build --pull || { env_set "$MOD_ENV_FILE" OBS_VERSION "$old"; die "build failed; version setting reverted, running services untouched"; }
  core_migrate
  dc up -d
  if ! wait_healthy 240 "${MOD_SERVICES[@]}"; then
    log_err "services are not healthy after the upgrade."
    [[ -n "${pre:-}" ]] && log_err "roll back with: obsctl core restore ${pre}  (after checking out the previous release)"
    return 1
  fi
  core_cli verify-audit || log_warn "audit chain verification reported a problem"
  log_info "core is running version ${new}"
}

# ---------------------------------------------------------------- remove / purge
core_remove() {
  local purge=0 confirm="" include_backups=0 confirm_backups=""
  while (( $# )); do
    case "$1" in
      --purge) purge=1; shift ;;
      --confirm-purge) confirm="$2"; shift 2 ;;
      --include-backups) include_backups=1; shift ;;
      --confirm-delete-backups) confirm_backups="$2"; shift 2 ;;
      -h|--help)
        cat <<'EOF'
Usage: obsctl core remove [--purge [--include-backups] [--confirm-purge "purge core"]
                                   [--confirm-delete-backups "delete core backups"]]

  (no flags)   Stop and remove the containers, network and systemd timers.
               ALL DATA IS KEPT: database, TLS state, configuration, secrets, backups.
               Bring it back with: obsctl core install
  --purge      ALSO delete the database volume, TLS state, configuration and secrets.
               Asks you to type "purge core". Backups are kept unless --include-backups.
EOF
        return 0 ;;
      *) die "unknown option for remove: $1" ;;
    esac
  done
  core_require_installed
  require_root core remove
  docker_ready || die "docker is not usable"

  if (( purge )); then
    local v list=""
    for v in "${MOD_VOLUMES[@]}"; do list="${list}    docker volume ${v}\n"; done
    confirm_typed "purge core" "$confirm" \
"PERMANENT DELETION of the core module:
$(printf '%b' "$list")    ${MOD_ENV_FILE} and ${MOD_CONF_DIR}
    secrets: ${MOD_SECRETS[*]}
$( ((include_backups)) && echo "    ALL core backups in ${OBS_BACKUP_DIR}" || echo "  Backups in ${OBS_BACKUP_DIR} are KEPT (and so is ${OBS_SECRETS_DIR}/backup_passphrase).")
Users, roles, the audit log and settings cannot be recovered without a backup."
    if (( include_backups )); then
      confirm_typed "delete core backups" "$confirm_backups" "This also deletes every encrypted core backup in ${OBS_BACKUP_DIR}."
    fi
  fi

  core_timers_set off
  if (( purge )); then
    log_info "removing containers, networks, volumes and local images"
    dc down --volumes --rmi local --remove-orphans
    rm -rf -- "$MOD_CONF_DIR"
    rm -f -- "$MOD_ENV_FILE"
    local s
    for s in "${MOD_SECRETS[@]}"; do rm -f -- "${OBS_SECRETS_DIR}/${s}"; done
    if (( include_backups )); then
      rm -f -- "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg "${OBS_BACKUP_DIR}"/obs-core_*.tar.gpg.sha256
    fi
    log_info "core purged"
  else
    log_info "removing containers and network (data is kept)"
    dc down --remove-orphans
    cat <<EOF

Core was removed. The following were KEPT:
  database volume:  obs-core-pgdata
  TLS state:        obs-core-caddy-data
  configuration:    ${MOD_ENV_FILE}, ${MOD_CONF_DIR}
  secrets:          ${OBS_SECRETS_DIR}
  backups:          ${OBS_BACKUP_DIR}
Restore service with: obsctl core install
EOF
  fi
}

# ---------------------------------------------------------------- dispatcher
core_main() {
  local verb="${1:-}"; shift || true
  case "$verb" in
    install) core_install "$@" ;;
    status) core_status "$@" ;;
    upgrade) core_upgrade "$@" ;;
    backup) core_backup "$@" ;;
    restore) core_restore "$@" ;;
    remove) core_remove "$@" ;;
    reconfigure) core_reconfigure "$@" ;;
    logs) core_logs "$@" ;;
    watchdog) core_watchdog "$@" ;;
    admin) core_admin "$@" ;;
    verify-audit) core_verify_audit "$@" ;;
    export-ca) core_export_ca "$@" ;;
    backup-key) core_backup_key "$@" ;;
    timers) core_timers "$@" ;;
    ""|-h|--help|help) core_usage ;;
    *) die "unknown core command: ${verb} (see: obsctl core --help)" ;;
  esac
}
