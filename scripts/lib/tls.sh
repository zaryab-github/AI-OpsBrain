# shellcheck shell=bash
# Internal certificate authority and server certificate management.

CA_DIR() { echo "$OPSBRAIN_ETC/ca"; }
TLS_DIR() { echo "$OPSBRAIN_ETC/tls"; }
WEB_UID=10001

tls_create_ca() {
  local ca_dir
  ca_dir=$(CA_DIR)
  if [[ -f $ca_dir/ca.crt && -f $ca_dir/ca.key ]]; then
    ok "Internal CA already exists ($ca_dir/ca.crt)"
    return 0
  fi
  install -d -m 0700 "$ca_dir" || die "Cannot create $ca_dir"
  info "Creating internal certificate authority"
  (
    umask 077
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$ca_dir/ca.key"
  ) || die "Could not create the CA key"
  openssl req -x509 -new -key "$ca_dir/ca.key" -sha256 -days 3650 \
    -subj "/O=AI-OpsBrain/CN=AI-OpsBrain Internal CA ($OPSBRAIN_HOSTNAME)" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" \
    -out "$ca_dir/ca.crt" || die "Could not create the CA certificate"
  chmod 0644 "$ca_dir/ca.crt"
  ok "CA certificate: $ca_dir/ca.crt (distribute this to browsers and agents)"
}

# tls_issue_server: issue/renew the server certificate for OPSBRAIN_HOSTNAME + OPSBRAIN_EXTRA_NAMES.
tls_issue_server() {
  local ca_dir tls_dir work san name
  ca_dir=$(CA_DIR)
  tls_dir=$(TLS_DIR)
  [[ -f $ca_dir/ca.key ]] || die "No internal CA at $ca_dir. Imported certificates are renewed with 'opsbrainctl cert import'."
  install -d -m 0755 "$tls_dir" || die "Cannot create $tls_dir"
  work=$(mktemp -d)

  san="DNS:$OPSBRAIN_HOSTNAME"
  for name in ${OPSBRAIN_EXTRA_NAMES:-}; do
    if [[ $name =~ ^[0-9.]+$ || $name == *:* ]]; then san+=",IP:$name"; else san+=",DNS:$name"; fi
  done
  cat >"$work/ext.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=$san
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
EOF
  (
    umask 077
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$work/server.key"
  ) || die "Could not create the server key"
  openssl req -new -key "$work/server.key" -subj "/O=AI-OpsBrain/CN=$OPSBRAIN_HOSTNAME" -out "$work/server.csr" ||
    die "Could not create the certificate request"
  # 397 days: the longest validity browsers accept for server certificates.
  openssl x509 -req -in "$work/server.csr" -CA "$ca_dir/ca.crt" -CAkey "$ca_dir/ca.key" -CAcreateserial \
    -days 397 -sha256 -extfile "$work/ext.cnf" -out "$work/server.crt" 2>/dev/null ||
    die "Could not sign the server certificate"
  cat "$work/server.crt" "$ca_dir/ca.crt" >"$work/fullchain.crt"
  tls_install_pair "$work/fullchain.crt" "$work/server.key"
  rm -rf "$work"
  printf 'internal-ca\n' >"$tls_dir/source"
  ok "Server certificate issued for: ${san//,/ }"
}

# Install a cert/key pair, overwriting in place so bind mounts keep seeing the same inode.
tls_install_pair() {
  local crt=$1 key=$2 tls_dir
  tls_dir=$(TLS_DIR)
  install -d -m 0755 "$tls_dir"
  [[ -f $tls_dir/server.key ]] || install -m 0640 /dev/null "$tls_dir/server.key"
  [[ -f $tls_dir/server.crt ]] || install -m 0644 /dev/null "$tls_dir/server.crt"
  cat "$key" >"$tls_dir/server.key"
  cat "$crt" >"$tls_dir/server.crt"
  # The web container runs as uid 10001 and must read the key; nobody else may.
  chown "root:$WEB_UID" "$tls_dir/server.key"
  chmod 0640 "$tls_dir/server.key"
  chmod 0644 "$tls_dir/server.crt"
}

tls_import() {
  local crt=$1 key=$2
  [[ -f $crt && -f $key ]] || die "Certificate or key file not found"
  openssl x509 -in "$crt" -noout >/dev/null 2>&1 || die "$crt is not a PEM certificate"
  openssl pkey -in "$key" -noout >/dev/null 2>&1 || die "$key is not a PEM private key (or is encrypted)"
  local a b
  a=$(openssl x509 -in "$crt" -noout -pubkey | openssl sha256)
  b=$(openssl pkey -in "$key" -pubout | openssl sha256)
  [[ $a == "$b" ]] || die "The certificate does not match the private key"
  openssl x509 -in "$crt" -noout -checkhost "$OPSBRAIN_HOSTNAME" | grep -q "does match" ||
    warn "Certificate is not valid for $OPSBRAIN_HOSTNAME — browsers will warn"
  tls_install_pair "$crt" "$key"
  printf 'imported\n' >"$(TLS_DIR)/source"
  ok "Imported certificate $(openssl x509 -in "$crt" -noout -subject)"
}

tls_days_left() {
  local crt end
  crt="$(TLS_DIR)/server.crt"
  [[ -s $crt ]] || {
    echo -1
    return
  }
  end=$(openssl x509 -in "$crt" -noout -enddate | cut -d= -f2)
  echo $((($(date -d "$end" +%s) - $(date +%s)) / 86400))
}

tls_show() {
  local crt
  crt="$(TLS_DIR)/server.crt"
  [[ -s $crt ]] || die "No server certificate installed"
  openssl x509 -in "$crt" -noout -subject -issuer -enddate -ext subjectAltName
  echo "source: $(cat "$(TLS_DIR)/source" 2>/dev/null || echo unknown)"
  echo "days left: $(tls_days_left)"
  [[ -f $(CA_DIR)/ca.crt ]] && echo "internal CA: $(CA_DIR)/ca.crt"
  return 0
}
