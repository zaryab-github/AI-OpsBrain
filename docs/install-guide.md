# Install guide

Phase 1 installs the **core** module: web UI, API, worker, PostgreSQL and the TLS proxy.
Logging, Monitoring and agents arrive in later phases and install the same way
(`obsctl logging ...`, `obsctl monitoring ...`).

## 1. Requirements

| Item | Requirement |
|---|---|
| OS | Linux with systemd (Ubuntu 22.04/24.04, Debian 12, RHEL/Rocky 9 tested by design) |
| CPU / RAM / disk | 2 vCPU, 4 GB RAM, 20 GB free for the core module alone |
| Software | Docker Engine 24+ with the Compose plugin (`docker compose version`), `openssl`, `gpg`, `curl`, `tar`, `git` |
| Ports | 80 and 443 free on the server (or choose others with `--http-port/--https-port`) |
| Access | root (`sudo`) |
| Internet | Needed **once**, to pull base images and Python/npm packages while building |

Check before you start:

```bash
docker version && docker compose version
openssl version && gpg --version | head -1
ss -ltnp | grep -E ':(80|443)\s' || echo "ports 80/443 are free"
df -h /var/lib/docker /var/backups
```

## 2. Get the code and put `obsctl` on the PATH

```bash
sudo git clone <YOUR-REPO-URL> /opt/obs
sudo ln -sf /opt/obs/bin/obsctl /usr/local/bin/obsctl
obsctl version
```

## 3. (Recommended) Pin dependency versions once

The images build without lock files, but then every build takes the newest allowed
versions. To make builds reproducible, generate the locks **once** on any machine with
Docker and internet access, and commit them:

```bash
cd /opt/obs && sudo ./scripts/lock-deps.sh
git add backend/requirements.txt frontend/package-lock.json
git commit -m "Pin dependencies"
```

## 4. Install the core module

Interactive (asks for hostname and the first administrator):

```bash
sudo obsctl core install
```

Non-interactive, with a generated one-time admin password printed once:

```bash
sudo obsctl core install \
  --hostname obs.example.internal \
  --tls internal \
  --admin-user admin \
  --admin-generate-password
```

TLS modes:

| Mode | When to use | Extra flags |
|---|---|---|
| `internal` (default) | Private hostname or IP. Caddy runs its own CA. | none |
| `acme` | Public DNS name reachable from the internet on 80/443 | `--acme-email you@example.com` |
| `custom` | You already have a certificate | `--cert /path/fullchain.pem --key /path/privkey.pem` |

What install does: checks preconditions, generates all secrets (random, mode 0440, never
overwritten on re-run), renders the Caddyfile, builds the images, starts PostgreSQL, runs
database migrations, starts API/worker/proxy, creates the first administrator, and installs
two systemd timers (health watchdog every 5 minutes, daily encrypted backup).

Install is safe to re-run: it reuses existing config, secrets and data.

### Do these two things immediately

```bash
# 1. Save the backup passphrase OFF this server (password manager). Without it a backup
#    cannot be restored on a new machine.
sudo obsctl core backup-key

# 2. With --tls internal: export the CA and trust it on every client machine/browser.
sudo obsctl core export-ca ./obs-root-ca.crt
```

On Windows, import `obs-root-ca.crt` into "Trusted Root Certification Authorities"; on
Ubuntu use `sudo cp obs-root-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`.

## 5. Verify the install

Run each check; the expected result is shown under it.

```bash
sudo obsctl core status
```
All five services (`postgres api worker proxy` plus the finished `migrate` job) show
`running/healthy` (migrate shows `exited/none`), last line `Overall: healthy`.

```bash
curl --cacert ./obs-root-ca.crt -fsS https://obs.example.internal/api/v1/system/health
```
Returns JSON with `"status":"ok"`.

```bash
sudo obsctl core watchdog
```
Every row is `ok`; exit code 0 (`echo $?`).

```bash
sudo obsctl core verify-audit
```
Reports the audit chain as intact.

```bash
systemctl list-timers 'obs-core-*'
```
Shows `obs-core-watchdog.timer` and `obs-core-backup.timer`.

Then open `https://<hostname>/`, sign in, and you will be asked to change the password
(and to enrol MFA if the "require MFA" setting is on).

## 6. Backup, restore, upgrade, remove

```bash
sudo obsctl core backup --label before-change      # encrypted .tar.gpg + .tar.gpg.sha256 in /var/backups/obs
sudo obsctl core restore /var/backups/obs/<file>.tar.gpg
sudo obsctl core upgrade                            # backs up first, rebuilds, migrates, restarts
sudo obsctl core remove                             # stops containers; KEEPS all data and config
sudo obsctl core remove --purge                     # asks you to type 'purge core' before deleting data
```

* `restore` first takes a safety backup of the current state, then asks you to type `restore core`.
* `remove --purge` never deletes backups or the backup passphrase unless you add
  `--include-backups` and type a second confirmation (`delete core backups`).
* Old backups are never pruned unless you set `--backup-keep N` at install or
  `OBS_BACKUP_KEEP=N` in `/etc/obs/core.env`.

### Move to a new server

1. Copy the `.tar.gpg` file, its `.tar.gpg.sha256` file and the passphrase to the new server.
2. `sudo obsctl core install --no-admin --hostname <new-name>`
3. Put the passphrase into `/etc/obs/secrets/backup_passphrase` (mode 0440) and run
   `sudo obsctl core restore <file>.tar.gpg`.

## 7. Where things live

| What | Path |
|---|---|
| Config | `/etc/obs/core.env`, `/etc/obs/core/Caddyfile` |
| Secrets | `/etc/obs/secrets/` (root:10001, 0440) |
| Backups | `/var/backups/obs/` |
| Database volume | Docker volume `obs-core-pgdata` |
| CA / certificates | Docker volume `obs-core-caddy-data` |

## 8. Status of this guide

Written in Phase 1. The commands above were exercised against a fake Docker in tests; the
real image build and first start have **not** been run by the author (see
`docs/PROGRESS.md`, "Unverified"). If a step here does not behave as described, see
`docs/troubleshooting.md` and send the output of `sudo obsctl core logs`.
