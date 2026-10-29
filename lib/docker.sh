#!/usr/bin/env bash
# docker.sh - docker / compose wrappers. A module sets MOD_PROJECT, MOD_ENV_FILE and
# MOD_COMPOSE_FILE before calling dc(). Sourced, never executed.
# shellcheck shell=bash

# dc <compose args...> : run `docker compose` for the current module
dc() {
  "${OBS_DOCKER}" compose --project-name "${MOD_PROJECT}" \
    --env-file "${MOD_ENV_FILE}" -f "${MOD_COMPOSE_FILE}" "$@"
}

# container_state <service> -> "<status>/<health>" or "missing"
container_state() {
  local cid
  cid="$(dc ps -aq "$1" 2>/dev/null | head -n 1 || true)"
  if [[ -z "$cid" ]]; then printf 'missing'; return 0; fi
  "${OBS_DOCKER}" inspect --format \
    '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$cid" 2>/dev/null || printf 'unknown'
}

# state_is_good <state> : running and (healthy or no healthcheck defined)
state_is_good() {
  case "$1" in
    running/healthy | running/none) return 0 ;;
    *) return 1 ;;
  esac
}

# wait_healthy <timeout-seconds> <service...> : poll until every service is running+healthy
wait_healthy() {
  local timeout="$1"; shift
  local deadline=$(( SECONDS + timeout )) svc state pending
  while (( SECONDS < deadline )); do
    pending=""
    for svc in "$@"; do
      state="$(container_state "$svc")"
      state_is_good "$state" || pending="${pending} ${svc}(${state})"
    done
    [[ -z "$pending" ]] && return 0
    sleep "${OBS_POLL_SECONDS:-3}"
  done
  log_err "timed out after ${timeout}s waiting for:${pending}"
  return 1
}

docker_ready() {
  have_cmd "${OBS_DOCKER}" || return 1
  "${OBS_DOCKER}" info >/dev/null 2>&1 || return 1
  "${OBS_DOCKER}" compose version >/dev/null 2>&1
}
