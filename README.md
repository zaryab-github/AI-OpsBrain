# AI-OpsBrain

An AI-powered centralized observability platform: logging, monitoring, alerting, incidents, reporting,
AIOps and controlled remediation — with **Logging and Monitoring as fully independent modules** per host.

The scope is defined by [docs/AI_Centralized_Observability_Platform_Architecture.pdf](docs/AI_Centralized_Observability_Platform_Architecture.pdf).
Build status and the phase plan are in [docs/PROGRESS.md](docs/PROGRESS.md).

## What works today (Phase 1 — core platform)

- HTTPS-only web UI and API behind Caddy, with an internal CA created at install time
- Users, two-factor authentication (TOTP), account lockout, server-side sessions with CSRF protection
- Six built-in roles (Admin, DevOps, NOC, Developer, Viewer, Auditor) and an editable permission matrix
- Append-only, hash-chained audit log with integrity verification and CSV export
- System settings, platform health (database, queue, worker, audit integrity, backups, certificate)
- `opsbrainctl` to install, check, upgrade, back up, restore and remove — removal keeps data unless you purge
- Encrypted daily backups (restic) to local disk, S3 or MinIO

The full navigation from the architecture document is present; pages of modules that are not built yet say so
plainly instead of showing sample data.

## Quick start

On an Ubuntu 24.04 / Debian 12 server with Docker Engine and the Compose plugin:

```bash
sudo git clone https://github.com/zaryab-github/AI-OpsBrain.git /opt/opsbrain
```

```bash
sudo /opt/opsbrain/scripts/opsbrainctl install core --hostname opsbrain.example.internal
```

Then follow the [install guide](docs/install-guide.md) to trust the CA certificate and sign in.

## Documentation

| Guide | For |
|---|---|
| [Install guide](docs/install-guide.md) | Installing, upgrading, backing up, restoring and removing the platform |
| [User guide](docs/user-guide.md) | Signing in, accounts, roles, audit log, settings |
| [Troubleshooting](docs/troubleshooting.md) | Problem → cause → fix, with commands |
| Agent guide | Arrives with Phase 2 (host agent) |

## Repository layout

```
backend/    FastAPI API, Celery worker, Alembic migrations, tests
frontend/   React + TypeScript UI (served by Caddy)
deploy/     Docker Compose per module, Caddy and PostgreSQL config, systemd timers
scripts/    opsbrainctl and its libraries
tests/      end-to-end lifecycle test and script tests
docs/       guides and progress log
```

## Development

```bash
scripts/dev/test-services.sh up
```

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest
```

```bash
cd frontend && npm ci && npm test && npm run build
```

```bash
bash tests/e2e/in-docker.sh
```

The last command runs the full install → backup → restore → upgrade → remove → purge lifecycle inside a
disposable Ubuntu container with its own Docker daemon.
