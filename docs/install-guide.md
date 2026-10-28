# Install guide

This guide covers the platform server: installing the core module, trusting its certificate, checking
status, upgrading, backups, restore and removal. Monitored hosts and the agent are covered in the agent guide
(Phase 2).

## 1. Server requirements

| | Minimum | Recommended for ≤100 hosts, ≤20 GB logs/day (all modules) |
|---|---|---|
| OS | Ubuntu 24.04 LTS or Debian 12 | same |
| CPU | 2 vCPU | 8 vCPU |
| RAM | 4 GB | 32 GB |
| Disk | 40 GB SSD | 500 GB+ SSD (logs and metrics) |
| Software | Docker Engine 24+ with the Compose v2 plugin, git, openssl | same |
| Network | TCP 443 (and 80 for the redirect) reachable from users | same; agents also use 443 |

Install Docker Engine from Docker's repository (the `docker.io` package from Ubuntu also works):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

## 2. Get the code

```bash
sudo git clone https://github.com/zaryab-github/AI-OpsBrain.git /opt/opsbrain
```

Install from a release tag in production (`sudo git -C /opt/opsbrain checkout v0.1.0`).

## 3. Install the core module

Pick the name users will type in the browser and make sure it resolves to this server in your DNS.

```bash
sudo /opt/opsbrain/scripts/opsbrainctl install core --hostname opsbrain.corp.example
```

What happens:

1. Checks Docker, Compose, openssl, OS and memory.
2. Writes `/etc/opsbrain/compose.env` and generates every password and key into `/etc/opsbrain/secrets/`
   (mode 0600, root only). **No default passwords exist anywhere.**
3. Creates an internal certificate authority (`/etc/opsbrain/ca/`) and a server certificate for the hostname
   plus this server's IP addresses (`--extra-names "10.0.0.5 opsbrain"` to choose them yourself).
4. Builds the images, starts PostgreSQL, Valkey, the migration job, API, worker and the Caddy web proxy, and
   waits until all are healthy.
5. Asks for the first administrator's username, email and password (at least 12 characters).
6. Links `/usr/local/bin/opsbrainctl` and enables two systemd timers: daily backup at 02:30 and a daily
   certificate expiry check.

Unattended install:

```bash
sudo opsbrainctl install core --hostname opsbrain.corp.example --admin-user alice --admin-email alice@corp.example --admin-password-file /root/admin.pw
```

Other ports: `--http-port 8080 --https-port 8443`.

**Save the backup password off the server now.** Backups are encrypted; without this password they cannot be
restored after losing the machine:

```bash
sudo grep RESTIC_PASSWORD /etc/opsbrain/secrets/backup.env
```

## 4. Trust the internal CA

Browsers will warn until they trust `/etc/opsbrain/ca/ca.crt`. Copy it to your workstation and:

- **Windows (all users):** `certutil -addstore -f Root ca.crt` in an elevated prompt, or distribute by Group Policy.
- **macOS:** `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt`
- **Ubuntu/Debian:** copy to `/usr/local/share/ca-certificates/opsbrain.crt`, then `sudo update-ca-certificates`.
- **Firefox:** Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import.

To use a certificate from your company CA instead:

```bash
sudo opsbrainctl cert import --cert /root/opsbrain-fullchain.pem --key /root/opsbrain.key
```

## 5. First sign-in

Open `https://<hostname>`, sign in as the administrator, and scan the QR code with an authenticator app — two-factor
authentication is required for administrators by default. Then add users under **Administration → Users**.

## 6. Day-to-day commands

| Task | Command |
|---|---|
| Health of everything (exit code 1 if anything is unhealthy) | `sudo opsbrainctl status` |
| Health of one module | `sudo opsbrainctl status core` |
| Back up now | `sudo opsbrainctl backup` |
| List backups | `sudo opsbrainctl backup --list` |
| Verify backup repository integrity | `sudo opsbrainctl backup --check` |
| Restore latest backup | `sudo opsbrainctl restore` |
| Restore a specific snapshot | `sudo opsbrainctl restore 4f1c2a9e` |
| Upgrade to the code in /opt/opsbrain | `sudo opsbrainctl upgrade` |
| Upgrade to a release tag | `sudo opsbrainctl upgrade --ref v0.2.0` |
| Show / renew / import the certificate | `sudo opsbrainctl cert show` · `cert renew` · `cert import --cert F --key F` |
| Service logs | `sudo opsbrainctl logs api -f` |
| Apply edited config files | `sudo opsbrainctl restart` (or `restart api worker`) |
| Verify audit log integrity | `sudo opsbrainctl verify-audit` |
| Recover access (new admin from the console) | `sudo opsbrainctl admin create` |
| Remove the core module (keeps all data) | `sudo opsbrainctl remove core` |
| Remove and delete all core data | `sudo opsbrainctl remove core --purge` |

## 7. Backups

- Daily at 02:30 (systemd timer `opsbrain-backup.timer`), keeping 7 daily, 4 weekly and 6 monthly snapshots.
- Each backup contains a PostgreSQL dump and the whole `/etc/opsbrain` (configuration, secrets, CA).
- Encrypted with restic. Default repository: `/var/lib/opsbrain/backup/restic` **on the same server** — set an
  off-server target for real protection. For S3 or MinIO edit `/etc/opsbrain/secrets/backup.env`:

  ```
  RESTIC_REPOSITORY=s3:https://minio.corp.example:9000/opsbrain-backups
  AWS_ACCESS_KEY_ID=...
  AWS_SECRET_ACCESS_KEY=...
  ```

- Backup results appear in `opsbrainctl status` and on **Administration → System Settings → Platform health**.

## 8. Restore

```bash
sudo opsbrainctl restore            # latest snapshot
```

Restore always takes a safety backup of the current state first, then asks you to type `restore`. It replaces the
platform database; add `--include-config` to also restore `/etc/opsbrain` (the current one is kept as
`/etc/opsbrain.pre-restore-<time>`).

**Disaster recovery onto a new server:** install Docker and the code, run `opsbrainctl install core` with the same
hostname, put the old `RESTIC_REPOSITORY`/`RESTIC_PASSWORD` into `/etc/opsbrain/secrets/backup.env`, then:

```bash
sudo opsbrainctl restore latest --include-config
```

## 9. Upgrade

`opsbrainctl upgrade` takes a pre-upgrade backup, rebuilds the images, runs database migrations and waits for
health. If it fails, it prints the rollback steps (check out the previous version, restore the pre-upgrade
snapshot).

## 10. Removal

- `opsbrainctl remove core` stops and removes the containers and timers. **Database, configuration, CA and backups
  stay.** Reinstalling reuses them, including all accounts.
- `opsbrainctl remove core --purge` takes a final backup, then asks you to type `purge core` and deletes the
  database volumes and `/etc/opsbrain`. Backups are still kept. Adding `--purge-backups` deletes them too, after a
  second typed confirmation.
- Scripts can confirm deliberately with `OPSBRAIN_CONFIRM_PHRASE="purge core"`; `--yes` never bypasses a typed
  confirmation.

## 11. Where things are

| Path | Contents |
|---|---|
| `/opt/opsbrain` | Code |
| `/etc/opsbrain/compose.env` | Hostname, ports, version |
| `/etc/opsbrain/secrets/` | Generated passwords and keys (root only) |
| `/etc/opsbrain/ca/`, `/etc/opsbrain/tls/` | Internal CA, server certificate |
| `/etc/opsbrain/state/modules.json` | Installed modules (read by the UI) |
| Docker volumes `opsbrain-core_postgres-data`, `opsbrain-core_valkey-data` | Platform database, queue |
| `/var/lib/opsbrain/backup/` | Local backup repository |
| `/var/lib/opsbrain/backup-status/status.json` | Result of the last backup |

## 12. Security notes

- Only Caddy publishes ports (80 → redirect, 443). PostgreSQL, Valkey and the API are on a private Docker network.
- TLS 1.2/1.3 only, HSTS, strict Content-Security-Policy, no framing, no `Server` header.
- Containers run as non-root with all Linux capabilities dropped and `no-new-privileges`; the API and worker have
  read-only file systems.
- The API connects with a least-privilege database role that cannot modify or delete audit records; a trigger
  blocks it for every role, and a hash chain detects tampering by anyone with superuser access.
- Membership of the `docker` group is equivalent to root on this server; keep it to administrators.
