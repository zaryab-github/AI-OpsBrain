# Shared bats helpers: a sandboxed /etc/obs and a fake `docker` that records every call.
REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
OBSCTL="${REPO_ROOT}/bin/obsctl"

setup_sandbox() {
  TMP="$(mktemp -d)"
  export TMP
  export OBS_ETC="${TMP}/etc"
  export OBS_BACKUP_DIR="${TMP}/backups"
  export OBS_SYSTEMD_DIR="${TMP}/systemd"
  export OBS_SKIP_ROOT_CHECK=1 OBS_SKIP_CHOWN=1 OBS_SKIP_SYSTEMD=1 OBS_POLL_SECONDS=0 OBS_MIN_FREE_KB=1
  export FAKE_DOCKER_LOG="${TMP}/docker.log"
  export NO_COLOR=1
  mkdir -p "${TMP}/bin" "${OBS_SYSTEMD_DIR}"
  : > "$FAKE_DOCKER_LOG"
  cp "${REPO_ROOT}/tests/obsctl/fake-docker" "${TMP}/bin/docker"
  cp "${REPO_ROOT}/tests/obsctl/fake-curl" "${TMP}/bin/curl"
  chmod +x "${TMP}/bin/docker" "${TMP}/bin/curl"
  export PATH="${TMP}/bin:${PATH}"
  export FAKE_HAS_USERS=1
  exec < /dev/null   # tests must never wait on an inherited terminal or pipe
}

teardown_sandbox() {
  [[ -n "${TMP:-}" && -d "$TMP" ]] && rm -rf "$TMP"
  return 0
}

# install with test-friendly defaults; extra args are appended
do_install() {
  run "$OBSCTL" core install --hostname obs.test.local --http-port 18080 --https-port 18443 \
    --backup-keep 0 --no-admin --no-timers "$@"
}

docker_log() { cat "$FAKE_DOCKER_LOG"; }
