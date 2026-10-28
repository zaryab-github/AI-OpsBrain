# AI-OpsBrain — AI Centralized Observability Platform

Source of truth for scope: `docs/AI_Centralized_Observability_Platform_Architecture.pdf`.
Current status, decisions and the phase plan: `docs/PROGRESS.md` — read it first in every new session.

## Working rules (from the project owner)
- Build one phase at a time. Test it, commit it, then STOP and wait for the owner's approval before the next phase.
- Never fake features or use dummy/sample data in the product. A page whose backing module isn't built yet says so; it never shows invented numbers.
- Never delete data without asking. Removal commands keep data by default; `--purge` must ask for confirmation.
- Logging and Monitoring are fully independent — per host (agent services) and per server module. Nothing in one may require the other. Only the AI/AIOps layer correlates them, via shared metadata (host_id, environment, application, service, time).
- Production-grade: TLS everywhere, no default passwords (installer generates secrets), RBAC, audit log, tests, backups, self-monitoring.
- Update `docs/PROGRESS.md` (and this file if conventions change) at the end of every phase.

## Layout and commands
- `backend/` FastAPI + Celery + Alembic. Venv at `backend/.venv`. `ruff check .`, `pytest` (integration tests need
  `scripts/dev/test-services.sh up`; they skip if services are absent unless `OPSBRAIN_REQUIRE_INTEGRATION=1`).
- `frontend/` React/TS/Vite. `npm test`, `npm run lint`, `npm run build`.
- `scripts/opsbrainctl` + `scripts/lib/*.sh` (bash, shellcheck-clean). `bash tests/scripts/test_opsbrainctl.sh`.
- `tests/e2e/in-docker.sh` runs the full server lifecycle in a disposable Ubuntu container with its own dockerd.
- `deploy/<module>/compose.yaml` — one Compose project per server module (`opsbrain-<module>`).
- New permissions go in `backend/app/security/permissions.py` (Admin gets them automatically; other built-in roles
  need a migration). New nav pages go in `frontend/src/layout/nav.ts` + `PAGES` in `App.tsx`.
- Every state-changing API route writes an audit entry via `app.services.audit.record` in the same transaction.

## Environment notes
- Dev machine is Windows 11; Docker Desktop (WSL2 backend) is used to build and test. Go is not installed locally — build/test Go inside Docker.
- Target production: one Ubuntu 24.04 / Debian 12 VM with Docker Compose. Monitored hosts: Ubuntu/Debian.
