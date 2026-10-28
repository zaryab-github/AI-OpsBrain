# shellcheck shell=bash
# Shared helpers for opsbrainctl. Sourced, never executed directly.

OPSBRAIN_ETC="${OPSBRAIN_ETC:-/etc/opsbrain}"
OPSBRAIN_VAR="${OPSBRAIN_VAR:-/var/lib/opsbrain}"
OPSBRAIN_BIN_LINK="${OPSBRAIN_BIN_LINK:-/usr/local/bin/opsbrainctl}"
OPSBRAIN_SYSTEMD_DIR="${OPSBRAIN_SYSTEMD_DIR:-/etc/systemd/system}"

ALL_MODULES=(core logging monitoring ai automation archive)
# Modules whose server components exist in this release.
# shellcheck disable=SC2034 # used by opsbrainctl and core.sh
AVAILABLE_MODULES=(core)

# shellcheck disable=SC2034 # colour variables are used across the sourced libraries
if [[ -t 1 ]]; then
  C_RED=$'\e[31m' C_GRN=$'\e[32m' C_YEL=$'\e[33m' C_BLU=$'\e[34m' C_DIM=$'\e[2m' C_OFF=$'\e[0m'
else
  C_RED="" C_GRN="" C_YEL="" C_BLU="" C_DIM="" C_OFF=""
fi

info() { printf '%s==>%s %s\n' "$C_BLU" "$C_OFF" "$*"; }
ok() { printf '%s ok%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%swarn%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
die() {
  printf '%serror%s %s\n' "$C_RED" "$C_OFF" "$*" >&2
  exit 1
}

require_root() {
  [[ ${OPSBRAIN_ALLOW_NON_ROOT:-0} == 1 || $EUID -eq 0 ]] || die "Run as root: sudo opsbrainctl $*"
}

have() { command -v "$1" >/dev/null 2>&1; }

in_list() {
  local needle=$1
  shift
  local x
  for x in "$@"; do [[ $x == "$needle" ]] && return 0; done
  return 1
}

check_module_name() {
  local m=$1
  in_list "$m" "${ALL_MODULES[@]}" || die "Unknown module '$m'. Modules: ${ALL_MODULES[*]}"
}

version() { tr -d '[:space:]' <"$OPSBRAIN_HOME/VERSION"; }

# Ask a yes/no question; default No. Non-interactive sessions get No unless --yes was given.
confirm() {
  local prompt=$1
  [[ ${ASSUME_YES:-0} == 1 ]] && return 0
  [[ -t 0 ]] || die "$prompt — refusing without a terminal. Re-run with --yes to confirm."
  local reply
  read -r -p "$prompt [y/N] " reply
  [[ $reply =~ ^[Yy]([Ee][Ss])?$ ]]
}

# Require the user to type an exact phrase. Used for destructive actions; --yes does NOT bypass it
# unless OPSBRAIN_CONFIRM_PHRASE is set to the same phrase (for scripted, deliberate use).
confirm_phrase() {
  local phrase=$1 what=$2
  if [[ -n ${OPSBRAIN_CONFIRM_PHRASE:-} ]]; then
    [[ $OPSBRAIN_CONFIRM_PHRASE == "$phrase" ]] && return 0
    die "OPSBRAIN_CONFIRM_PHRASE does not match '$phrase'"
  fi
  [[ -t 0 ]] || die "$what needs interactive confirmation (or OPSBRAIN_CONFIRM_PHRASE='$phrase')."
  printf '%s%s%s\n' "$C_RED" "$what" "$C_OFF"
  local reply
  read -r -p "Type '$phrase' to continue: " reply
  [[ $reply == "$phrase" ]] || die "Confirmation did not match. Nothing was changed."
}

random_secret() {
  # 32 bytes of randomness, URL/env safe.
  openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48
}

# ---- module state -----------------------------------------------------------------------------

modules_file() { echo "$OPSBRAIN_ETC/state/modules.json"; }

module_installed() {
  local f
  f=$(modules_file)
  [[ -f $f ]] && grep -q "\"$1\"[[:space:]]*:" "$f"
}

# modules.json is read by the API; written atomically, keeping the inode for bind mounts.
write_modules_file() {
  local tmp f
  f=$(modules_file)
  tmp=$(mktemp "$OPSBRAIN_ETC/state/.modules.XXXXXX")
  {
    printf '{"modules": {'
    local first=1 m
    for m in "$@"; do
      [[ $first == 1 ]] || printf ', '
      first=0
      printf '%s' "$m"
    done
    printf '}}\n'
  } >"$tmp"
  chmod 0644 "$tmp"
  if [[ -f $f ]]; then cat "$tmp" >"$f" && rm -f "$tmp"; else mv "$tmp" "$f"; fi
}

# Print the JSON fragment for every installed module except $1 (used to rebuild the file).
installed_fragments_except() {
  local skip=$1 f
  f=$(modules_file)
  [[ -f $f ]] || return 0
  # Each module entry is written on its own as "name": {...} without nested braces.
  grep -o '"[a-z]*": {[^{}]*}' "$f" | grep -v "^\"$skip\":" || true
}

set_module_installed() {
  local m=$1 frag
  frag="\"$m\": {\"version\": \"$(version)\", \"installed_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
  local others=()
  mapfile -t others < <(installed_fragments_except "$m")
  write_modules_file "${others[@]}" "$frag"
}

set_module_removed() {
  local m=$1 others=()
  mapfile -t others < <(installed_fragments_except "$m")
  write_modules_file "${others[@]}"
}

installed_modules() {
  local m
  for m in "${ALL_MODULES[@]}"; do module_installed "$m" && echo "$m"; done
  return 0
}

# ---- docker compose -----------------------------------------------------------------------------

compose() {
  local module=$1
  shift
  docker compose -p "opsbrain-$module" -f "$OPSBRAIN_HOME/deploy/$module/compose.yaml" \
    --env-file "$OPSBRAIN_ETC/compose.env" "$@"
}

check_docker() {
  have docker || die "Docker is not installed. Install Docker Engine: https://docs.docker.com/engine/install/"
  docker info >/dev/null 2>&1 || die "Docker is installed but not running (try: systemctl start docker)."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is missing (package docker-compose-plugin)."
}

# Wait until every service with a healthcheck in the module reports healthy.
wait_healthy() {
  local module=$1 timeout=${2:-240} waited=0 unhealthy
  while ((waited < timeout)); do
    unhealthy=$(compose "$module" ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null |
      awk '$1 != "migrate" && ($2 != "running" || ($3 != "" && $3 != "healthy"))')
    [[ -z $unhealthy ]] && return 0
    sleep 3
    waited=$((waited + 3))
  done
  warn "Services not healthy after ${timeout}s:"
  printf '%s\n' "$unhealthy" >&2
  return 1
}

write_env_file() {
  # write_env_file PATH MODE KEY=VALUE...
  local path=$1 mode=$2
  shift 2
  local tmp
  tmp=$(mktemp "$(dirname "$path")/.env.XXXXXX")
  chmod "$mode" "$tmp"
  printf '%s\n' "$@" >"$tmp"
  mv "$tmp" "$path"
}

env_get() {
  # env_get FILE KEY -> value (first match)
  local file=$1 key=$2
  [[ -f $file ]] || return 1
  sed -n "s/^${key}=//p" "$file" | head -n1
}
