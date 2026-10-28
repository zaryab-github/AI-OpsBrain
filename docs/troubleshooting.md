# Troubleshooting

Start every investigation with:

```bash
sudo opsbrainctl status
```

Each entry below is **problem → cause → fix**.

---

### Install stops with "Docker is installed but not running"

- **Cause:** the Docker daemon is stopped.
- **Fix:**
  ```bash
  sudo systemctl enable --now docker
  ```

### Install stops with "Docker Compose v2 plugin is missing"

- **Cause:** only the old `docker-compose` (v1) or no Compose is installed.
- **Fix (Ubuntu/Debian):**
  ```bash
  sudo apt-get install -y docker-compose-plugin || sudo apt-get install -y docker-compose-v2
  ```

### Install or upgrade ends with "Core did not become healthy"

- **Cause:** one service failed to start; the message lists which.
- **Fix:** read that service's log, then re-run the command (install and upgrade are safe to repeat).
  ```bash
  sudo opsbrainctl logs api
  ```
  ```bash
  sudo opsbrainctl logs migrate
  ```
  ```bash
  sudo opsbrainctl logs postgres
  ```

### Port 80 or 443 already in use

- **Cause:** another web server (nginx, apache) runs on the host. `docker compose` reports
  `bind: address already in use`.
- **Fix:** stop the other server, or install on other ports:
  ```bash
  sudo ss -ltnp | grep -E ':(80|443) '
  ```
  ```bash
  sudo opsbrainctl install core --http-port 8080 --https-port 8443
  ```

### Browser shows "Your connection is not private" / NET::ERR_CERT_AUTHORITY_INVALID

- **Cause:** the browser does not trust the internal CA.
- **Fix:** install `/etc/opsbrain/ca/ca.crt` as a trusted root on the workstation (install guide §4).

### Browser shows NET::ERR_CERT_COMMON_NAME_INVALID

- **Cause:** you opened the platform by a name or IP that is not in the certificate.
- **Fix:** check the names, then reissue the certificate with the missing name:
  ```bash
  sudo opsbrainctl cert show
  ```
  ```bash
  sudo sed -i 's/^OPSBRAIN_EXTRA_NAMES=.*/OPSBRAIN_EXTRA_NAMES=10.0.0.5 opsbrain/' /etc/opsbrain/compose.env && sudo opsbrainctl cert renew
  ```

### "Certificate expires in N days" warning

- **Cause:** the daily renewal timer is not running, or the certificate was imported from another CA.
- **Fix:** for the internal CA, renew now and check the timer; for imported certificates, import the new one.
  ```bash
  sudo opsbrainctl cert renew
  ```
  ```bash
  systemctl list-timers 'opsbrain-*'
  ```

### Page loads but shows "Sign-in not complete" or returns to the sign-in page

- **Cause:** the session expired (30 min idle / 12 h total by default), was signed out by a password change, or
  the browser blocks cookies for the site.
- **Fix:** sign in again. If it happens immediately every time, check that the site is opened over **https** and
  that the system clock of the server is correct:
  ```bash
  timedatectl
  ```

### "Invalid username or password, or the account is locked"

- **Cause:** wrong credentials, a deactivated account, or a lockout after repeated failures. The message is the same
  for all cases on purpose.
- **Fix:** an administrator checks **Administration → Users** (status column) and uses **Unlock**,
  **Reset password** or **Reactivate**. The reason is recorded in **Audit Logs** (filter action `auth.login`,
  result `failure`).

### Two-factor code always rejected

- **Cause:** the phone's clock is off by more than 30 seconds, or the code was already used (codes are single-use).
- **Fix:** enable automatic time on the phone and wait for the next code. If the authenticator is lost, an
  administrator uses **Reset 2FA** on the user.

### Every administrator is locked out or lost their authenticator

- **Cause:** no one can sign in with admin rights.
- **Fix:** create a new administrator from the server console:
  ```bash
  sudo opsbrainctl admin create
  ```

### "Too many sign-in attempts. Try again later."

- **Cause:** more than 30 sign-in attempts from one IP address in 5 minutes (protects against password guessing).
- **Fix:** wait 5 minutes. If many users share one NAT address and hit this legitimately, raise
  `OPSBRAIN_LOGIN_IP_LIMIT` in `/etc/opsbrain/secrets/app.env`, then:
  ```bash
  sudo opsbrainctl restart api
  ```

### Platform health: "No heartbeat from the background worker"

- **Cause:** the worker container stopped or cannot reach Valkey.
- **Fix:**
  ```bash
  sudo opsbrainctl logs worker
  ```
  ```bash
  sudo opsbrainctl restart worker
  ```

### Platform health: "Audit log integrity" is critical

- **Cause:** an audit entry was modified or removed outside the platform (someone with database superuser or
  filesystem access). This is a security event.
- **Fix:** do not "repair" it. Note the reported entry id, preserve evidence (take a backup), investigate host access,
  and compare with an earlier backup restored on a separate machine.
  ```bash
  sudo opsbrainctl verify-audit
  ```

### `opsbrainctl backup` fails with "cannot open or initialise the backup repository"

- **Cause:** wrong `RESTIC_REPOSITORY`, wrong credentials for S3/MinIO, or the target is unreachable.
- **Fix:** check the settings and try the repository directly:
  ```bash
  sudo grep -v PASSWORD /etc/opsbrain/secrets/backup.env
  ```
  ```bash
  sudo opsbrainctl backup --list
  ```

### Backup fails with "pg_dump failed"

- **Cause:** PostgreSQL is not running or the disk is full.
- **Fix:**
  ```bash
  sudo opsbrainctl status core
  ```
  ```bash
  df -h /var/lib/docker /var/lib/opsbrain
  ```

### Restore says "Snapshot '…' not found"

- **Cause:** a typo, or the snapshot was pruned by the retention policy.
- **Fix:** list snapshots and use an id from the list:
  ```bash
  sudo opsbrainctl backup --list
  ```

### Restore fails with "pg_restore failed"

- **Cause:** the dump is from a newer platform version than the code installed, or it is damaged.
- **Fix:** check out the version the snapshot was made with (the snapshot carries a `v<version>` tag), run
  `opsbrainctl upgrade`, then restore again. The safety backup taken before the failed restore holds your previous
  state:
  ```bash
  sudo opsbrainctl backup --list
  ```

### `opsbrainctl remove core` says "Remove these modules first"

- **Cause:** other modules depend on the core.
- **Fix:** remove them first (their data is kept too), then core.

### Purge refuses with "needs interactive confirmation"

- **Cause:** purge was run from a script or without a terminal; it never deletes data without an explicit
  confirmation.
- **Fix:** run it in a terminal and type the phrase, or confirm deliberately in a script:
  ```bash
  sudo OPSBRAIN_CONFIRM_PHRASE="purge core" opsbrainctl remove core --purge
  ```

### Status shows "disk … used" warning or critical

- **Cause:** the Docker data disk is above 80 % / 90 %.
- **Fix:** find what grows; remove unused Docker images (never volumes) and old local backups only after copying
  them off the server:
  ```bash
  sudo du -sh /var/lib/docker/volumes/* /var/lib/opsbrain/* | sort -h | tail
  ```
  ```bash
  sudo docker image prune -a
  ```
