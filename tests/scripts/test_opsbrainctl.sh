#!/usr/bin/env bash
# shellcheck disable=SC2031,SC2034 # assert() subshells; WEB_UID is read by the sourced tls.sh
# Unit tests for opsbrainctl library functions that do not need Docker.
# Run: bash tests/scripts/test_opsbrainctl.sh
set -uo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export OPSBRAIN_HOME=$REPO OPSBRAIN_ETC=$TMP/etc OPSBRAIN_VAR=$TMP/var
# Git Bash on Windows would rewrite openssl's "/O=.../CN=..." subject into a file path.
export MSYS2_ARG_CONV_EXCL="/O="
# shellcheck source=scripts/lib/common.sh
. "$REPO/scripts/lib/common.sh"
# shellcheck source=scripts/lib/tls.sh
. "$REPO/scripts/lib/tls.sh"
if [[ $(uname -s) != Linux ]]; then
  # Developer convenience on Git Bash: NTFS cannot take Unix modes or owners (CI runs on Linux).
  install() {
    local args=() skip=0 a
    for a in "$@"; do
      if ((skip)); then
        skip=0
        continue
      fi
      if [[ $a == -m ]]; then
        skip=1
        continue
      fi
      args+=("$a")
    done
    command install "${args[@]}"
  }
  chown() { :; }
fi

PASS=0 FAILS=0
assert() {
  local desc=$1
  shift
  if "$@"; then
    PASS=$((PASS + 1))
    echo "  ok   $desc"
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL $desc"
  fi
}

echo "module state file"
mkdir -p "$OPSBRAIN_ETC/state"
assert "nothing installed initially" bash -c "[[ -z \"$(installed_modules)\" ]]"
set_module_installed core
assert "core recorded" module_installed core
assert "logging not recorded" bash -c "! grep -q logging '$OPSBRAIN_ETC/state/modules.json'"
set_module_installed logging
assert "both recorded" bash -c "[[ \"$(installed_modules | tr '\n' ' ')\" == 'core logging ' ]]"
set_module_installed core
assert "re-recording keeps a single entry" bash -c "[[ \$(grep -o '\"core\"' '$OPSBRAIN_ETC/state/modules.json' | wc -l) == 1 ]]"
json_valid() {
  local f=$1 py
  have cygpath && f=$(cygpath -w "$f")
  for py in python3 python; do
    "$py" -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>/dev/null && return 0
  done
  return 1
}
assert "modules.json is valid JSON" json_valid "$OPSBRAIN_ETC/state/modules.json"
inode_before=$(stat -c %i "$OPSBRAIN_ETC/state/modules.json")
set_module_removed logging
inode_after=$(stat -c %i "$OPSBRAIN_ETC/state/modules.json")
assert "removal drops the module" bash -c "! grep -q logging '$OPSBRAIN_ETC/state/modules.json'"
assert "file rewritten in place (bind mounts keep working)" test "$inode_before" == "$inode_after"

echo "confirmations"
( . "$REPO/scripts/lib/common.sh"; confirm_phrase "purge core" "x" </dev/null ) >/dev/null 2>&1
assert "confirm_phrase fails non-interactively" test $? -ne 0
( . "$REPO/scripts/lib/common.sh"; OPSBRAIN_CONFIRM_PHRASE="purge core" confirm_phrase "purge core" "x" ) >/dev/null 2>&1
assert "matching OPSBRAIN_CONFIRM_PHRASE is accepted" test $? -eq 0
( . "$REPO/scripts/lib/common.sh"; OPSBRAIN_CONFIRM_PHRASE="yes" confirm_phrase "purge core" "x" ) >/dev/null 2>&1
assert "a different phrase is rejected" test $? -ne 0
( . "$REPO/scripts/lib/common.sh"; ASSUME_YES=1 confirm "ok?" ) >/dev/null 2>&1
assert "--yes answers y/N questions" test $? -eq 0
( . "$REPO/scripts/lib/common.sh"; confirm "ok?" </dev/null ) >/dev/null 2>&1
assert "y/N question refuses without terminal or --yes" test $? -ne 0

echo "secrets and env files"
s1=$(random_secret)
s2=$(random_secret)
assert "random secrets are long" test "${#s1}" -ge 40
assert "random secrets differ" test "$s1" != "$s2"
assert "random secrets are URL-safe" bash -c "[[ '$s1' =~ ^[A-Za-z0-9]+$ ]]"
mkdir -p "$TMP/envdir"
write_env_file "$TMP/envdir/x.env" 0600 "A=1" "B=two=2"
assert "env_get reads values containing '='" test "$(env_get "$TMP/envdir/x.env" B)" == "two=2"
if [[ $(uname -s) == Linux ]]; then
  assert "env file mode is 600" test "$(stat -c %a "$TMP/envdir/x.env")" == 600
fi

echo "internal CA and server certificate"
if have openssl; then
  export OPSBRAIN_HOSTNAME=opsbrain.test OPSBRAIN_EXTRA_NAMES="10.1.2.3 alt.opsbrain.test"
  WEB_UID=$(id -u) # tls_install_pair chowns the key to this uid
  (tls_create_ca) >"$TMP/tls.log" 2>&1 || cat "$TMP/tls.log"
  assert "CA created" test -s "$OPSBRAIN_ETC/ca/ca.crt"
  assert "CA is a CA" bash -c "openssl x509 -in '$OPSBRAIN_ETC/ca/ca.crt' -noout -ext basicConstraints | grep -q 'CA:TRUE'"
  (tls_issue_server) >"$TMP/tls.log" 2>&1 || cat "$TMP/tls.log"
  crt=$OPSBRAIN_ETC/tls/server.crt
  assert "server certificate issued" test -s "$crt"
  assert "certificate chains to the CA" bash -c "openssl verify -CAfile '$OPSBRAIN_ETC/ca/ca.crt' '$crt' >/dev/null"
  sans=$(openssl x509 -in "$crt" -noout -ext subjectAltName)
  assert "SAN has hostname" bash -c "[[ '$sans' == *'DNS:opsbrain.test'* ]]"
  assert "SAN has IP" bash -c "[[ '$sans' == *'IP Address:10.1.2.3'* ]]"
  assert "SAN has extra DNS" bash -c "[[ '$sans' == *'DNS:alt.opsbrain.test'* ]]"
  assert "server cert is not a CA" bash -c "openssl x509 -in '$crt' -noout -ext basicConstraints | grep -q 'CA:FALSE'"
  days=$(tls_days_left)
  assert "validity about 397 days" bash -c "(( $days >= 395 && $days <= 397 ))"
  key=$OPSBRAIN_ETC/tls/server.key
  assert "key matches certificate" bash -c "[[ -s '$key' ]] && [[ \$(openssl x509 -in '$crt' -noout -pubkey | openssl sha256) == \$(openssl pkey -in '$key' -pubout | openssl sha256) ]]"
  (tls_import "$OPSBRAIN_ETC/ca/ca.crt" "$key") >/dev/null 2>&1
  assert "import refuses a key that does not match" test $? -ne 0
else
  echo "  skip (openssl not installed)"
fi

echo
echo "$PASS passed, $FAILS failed"
((FAILS == 0))
