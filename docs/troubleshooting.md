# Troubleshooting (Phase 1: Core)

Format: **Problem** -> likely cause -> fix. Always start with:

```bash
sudo obsctl core status
sudo obsctl core watchdog
sudo obsctl core logs api        # also: postgres, migrate, worker, proxy
```

## Install

**`error: this command must run as root`** -> not using sudo -> `sudo obsctl core install`.

**`docker is not usable` / `docker compose` missing** -> Docker or the Compose plugin not installed, or
your user/daemon is down -> `sudo systemctl enable --now docker`; `docker compose version`.

**Install stops at the preflight: port 80/443 in use** -> another web server holds the port ->
find it with `sudo ss -ltnp | grep -E ':(80|443)\s'`, stop it, or install with
`--http-port 8080 --https-port 8443`.

**Install stops at the preflight: not enough free disk** -> `df -h /var/lib/docker`; free space or move Docker's data-root.

**Image build fails while downloading packages** (`pip`/`npm` errors, timeouts, 403) -> the server cannot
reach PyPI, npm or Docker Hub (proxy/firewall) -> test `curl -sI https://pypi.org`, `curl -sI https://registry.npmjs.org`,
`docker pull python:3.12-slim`. Configure the proxy for Docker (`/etc/systemd/system/docker.service.d/http-proxy.conf`) and for
the build, or allow those hosts through the firewall. Re-run `sudo obsctl core install`; it resumes safely.

**Frontend build fails with a TypeScript or Vite error** -> the UI code in this phase could not be built by its
author. Send the last 60 lines of the install output (`sudo obsctl core install 2>&1 | tail -60`) so it can be fixed.

**`npm ci` fails: lock file out of sync** -> `package.json` changed after the lock was made -> run `./scripts/lock-deps.sh` and commit.

## Sign-in and access

**Browser warns "connection not private"** -> internal CA not trusted on this client -> `sudo obsctl core export-ca ./obs-root-ca.crt`,
import it into the client's trust store (see install guide).

**`curl: (60) SSL certificate problem`** -> same cause -> add `--cacert obs-root-ca.crt`.

**Login says "Invalid username or password" for a correct password** -> account locked, or user disabled ->
`sudo obsctl core admin unlock --user NAME`; check Users page.

**Forgot the only admin's password** -> `sudo obsctl core admin reset-password --user NAME --generate-password` (prints a one-time password, or omit `--generate-password` to type one).

**Lost the MFA device and recovery codes** -> `sudo obsctl core admin disable-mfa --user NAME`; the user re-enrols after signing in.

**Sign-in works but pages show "Your session expired" in a loop** -> the browser clock is far off, or cookies are blocked
for the site -> fix the clock (`timedatectl`), allow cookies for the host, open the site by the exact hostname used at install.

**"Access denied" on a page** -> the role lacks the permission -> Administration > Roles & RBAC, or ask an administrator.

## Running system

**A service shows `unhealthy` or `restarting`** -> read its log: `sudo obsctl core logs <service>`.
Common causes below.

**`migrate` exited with an error / API never starts** -> database not ready, or schema mismatch ->
`sudo obsctl core logs migrate` and `... logs postgres`. A message about a password means
`/etc/obs/secrets/core_db_password` does not match the existing database volume (for example after
copying files by hand); restore from backup with `obsctl core restore` rather than editing.

**System health shows `worker.heartbeat` critical** -> worker container stopped -> `sudo obsctl core logs worker`; `sudo obsctl core status`; restart everything with `sudo obsctl core upgrade` (safe: takes a backup first).

**System health shows `audit.chain` critical** -> the audit log failed verification (possible tampering or a restore from an
inconsistent file) -> `sudo obsctl core verify-audit` prints the first broken entry. Do not delete anything; keep a backup
and investigate who had database access.

**Watchdog reports certificate expiring** -> with `acme` check ports 80/443 reach the server and DNS is correct
(`sudo obsctl core logs proxy`); with `custom` replace the files and run `sudo obsctl core reconfigure --tls custom --cert F --key F`;
`internal` renews itself.

**Watchdog reports last backup too old / backup failed** -> `sudo obsctl core backup`; check free space in `/var/backups/obs`;
`systemctl status obs-core-backup.service` and `journalctl -u obs-core-backup.service -n 50`.

**Timers not running** -> `sudo obsctl core timers on`; `systemctl list-timers 'obs-core-*'`.

## Backup and restore

**`restore` says checksum mismatch** -> file damaged in transit -> copy it again and compare `sha256sum`.

**`restore` says bad passphrase / decryption failed** -> wrong passphrase -> use the one from the original server
(`obsctl core backup-key` there). Put it in `/etc/obs/secrets/backup_passphrase`.

**Upgrade failed half-way** -> `upgrade` took a backup first (see `/var/backups/obs`, label `pre-upgrade`) ->
`sudo obsctl core restore <that file>`.

## Removing

**I removed the module; is my data gone?** -> No. `remove` keeps volumes, config and backups. Run `sudo obsctl core install` to bring it back.

**`remove --purge` refuses to run** -> it needs the typed confirmation; run it in a terminal and type `purge core` when asked.

## Still stuck

Collect and send: `sudo obsctl core status --json`, `sudo obsctl core watchdog`, and the last 100 lines of the failing
service (`sudo obsctl core logs <service> | tail -100`). Secrets are not printed by these commands.
