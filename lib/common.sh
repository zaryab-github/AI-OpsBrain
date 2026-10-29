#!/usr/bin/env bash
# common.sh - helpers shared by every obsctl module. Sourced, never executed.
# shellcheck shell=bash

# ---- locations (all overridable through the environment, which the tests use) ----
: "${OBS_ETC:=/etc/obs}"
: "${OBS_BACKUP_DIR:=/var/backups/obs}"
: "${OBS_SYSTEMD_DIR:=/etc/systemd/system}"
: "${OBS_DOCKER:=docker}"
: "${OBS_CONTAINER_GID:=10001}"

OBS_SECRETS_DIR="${OBS_ETC}/secrets"

# ---- output ----
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_RED=""; C_YEL=""; C_GRN=""; C_DIM=""; C_OFF=""
fi

log_info() { printf '%s\n' "${C_GRN}==>${C_OFF} $*"; }
log_warn() { printf '%s\n' "${C_YEL}warning:${C_OFF} $*" >&2; }
log_err()  { printf '%s\n' "${C_RED}error:${C_OFF} $*" >&2; }
log_dim()  { printf '%s\n' "${C_DIM}$*${C_OFF}"; }
die()      { log_err "$*"; exit 1; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

systemd_usable() { have_cmd systemctl && [[ "${OBS_SKIP_SYSTEMD:-0}" != "1" ]]; }

ts_utc() { date -u +%Y%m%dT%H%M%SZ; }

is_tty() { [[ -t 0 && -t 1 ]]; }

# ---- temp dirs removed on exit (also after die) ----
OBS_TMP_DIRS=()
register_tmp() { OBS_TMP_DIRS+=("$1"); }
obs_cleanup() {
  local d
  for d in ${OBS_TMP_DIRS[@]+"${OBS_TMP_DIRS[@]}"}; do
    [[ -n "$d" && -d "$d" ]] && rm -rf -- "$d"
  done
  return 0
}

# ---- privilege ----
require_root() {
  if [[ "${OBS_SKIP_ROOT_CHECK:-0}" == "1" ]]; then return 0; fi
  [[ "$(id -u)" -eq 0 ]] || die "this command must run as root (try: sudo obsctl $*)"
}

# ---- prompts ----
# prompt_default "Question" "default" -> echoes the answer
prompt_default() {
  local question="$1" default="${2:-}" answer
  if ! is_tty; then printf '%s' "$default"; return 0; fi
  read -r -p "${question} [${default}]: " answer </dev/tty
  printf '%s' "${answer:-$default}"
}

# confirm_yes "Question" -> returns 0 on yes. -y / OBS_ASSUME_YES answers yes.
# Never used for destructive operations; those use confirm_typed.
confirm_yes() {
  local question="$1" answer
  if [[ "${OBS_ASSUME_YES:-0}" == "1" ]]; then return 0; fi
  is_tty || return 1
  read -r -p "${question} [y/N]: " answer </dev/tty
  [[ "$answer" == "y" || "$answer" == "Y" || "$answer" == "yes" ]]
}

# confirm_typed "<phrase>" "<value supplied by flag, may be empty>" "<what will happen>"
# Destructive operations require the exact phrase, typed or passed explicitly.
confirm_typed() {
  local phrase="$1" supplied="${2:-}" message="$3" typed
  printf '\n%s\n\n' "$message" >&2
  if [[ -n "$supplied" ]]; then
    [[ "$supplied" == "$phrase" ]] || die "confirmation text does not match; expected exactly: ${phrase}"
    return 0
  fi
  is_tty || die "refusing to continue without confirmation (not a terminal). Re-run interactively, or pass the confirmation flag with the exact text: ${phrase}"
  read -r -p "Type '${phrase}' to continue, anything else aborts: " typed </dev/tty
  [[ "$typed" == "$phrase" ]] || die "aborted, nothing was changed"
}

# prompt_secret_twice "Label" -> echoes the secret; fails when empty or mismatched
prompt_secret_twice() {
  local label="$1" a b
  is_tty || die "cannot prompt for ${label}: not a terminal"
  read -r -s -p "${label}: " a </dev/tty; printf '\n' >&2
  read -r -s -p "${label} (again): " b </dev/tty; printf '\n' >&2
  [[ -n "$a" ]] || die "${label} must not be empty"
  [[ "$a" == "$b" ]] || die "the two entries do not match"
  printf '%s' "$a"
}

# ---- randomness / secrets ----
# rand_b64url <bytes> -> URL-safe base64 without padding
rand_b64url() {
  local bytes="${1:-32}"
  openssl rand -base64 "$bytes" | tr -d '\n=' | tr '+/' '-_'
}

# rand_fernet_key -> a valid 32-byte url-safe base64 (padded) Fernet key
rand_fernet_key() {
  openssl rand -base64 32 | tr -d '\n' | tr '+/' '-_'
}

# write_secret <name> <value> [force]  - writes ${OBS_SECRETS_DIR}/<name> mode 0440 root:<gid>
# An existing secret is NEVER replaced unless force=force.
write_secret() {
  local value="$2" force="${3:-}" path="${OBS_SECRETS_DIR}/$1"
  if [[ -e "$path" && "$force" != "force" ]]; then return 0; fi
  ( umask 077; printf '%s' "$value" > "${path}.tmp" )
  mv -f "${path}.tmp" "$path"
  fix_secret_perms "$path"
}

fix_secret_perms() {
  local path="$1"
  chmod 0440 "$path"
  if [[ "${OBS_SKIP_CHOWN:-0}" != "1" ]]; then
    chown "root:${OBS_CONTAINER_GID}" "$path"
  fi
}

# ---- env file helpers (KEY=VALUE, no quoting, no spaces in values) ----
# env_get <file> <key> [default]
env_get() {
  local file="$1" key="$2" default="${3:-}" line
  if [[ -r "$file" ]]; then
    line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
    if [[ -n "$line" ]]; then printf '%s' "${line#*=}"; return 0; fi
  fi
  printf '%s' "$default"
}

# env_set <file> <key> <value> : replaces in place (keeping line order) or appends
env_set() {
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp "${file}.XXXXXX")"
  if [[ -f "$file" ]] && grep -qE "^${key}=" "$file"; then
    ENV_K="$key" ENV_V="$value" awk '
      index($0, ENVIRON["ENV_K"] "=") == 1 { print ENVIRON["ENV_K"] "=" ENVIRON["ENV_V"]; next }
      { print }' "$file" > "$tmp"
  else
    if [[ -f "$file" ]]; then cat "$file" > "$tmp"; fi
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  chmod 0640 "$tmp"
  mv -f "$tmp" "$file"
}

# ---- misc ----
human_bytes() {
  local b="$1"
  if have_cmd numfmt; then numfmt --to=iec --suffix=B "$b"; else printf '%sB' "$b"; fi
}

# valid_hostname <value> : DNS name, IPv4 address, or bracket-free IPv6
valid_hostname() {
  local v="$1"
  [[ -n "$v" && ${#v} -le 253 ]] || return 1
  [[ "$v" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] && return 0
  [[ "$v" =~ ^[0-9a-fA-F:]+$ && "$v" == *:* ]] && return 0
  return 1
}

valid_username() { [[ "$1" =~ ^[a-z][a-z0-9._-]{2,31}$ ]]; }

valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 )); }
