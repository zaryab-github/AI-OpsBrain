# CLAUDE.md - AI Centralized Observability Platform

Standalone project. Source of truth for scope:
`docs/AI_Centralized_Observability_Platform_Architecture.pdf` (7 pages).
Read it first in every new session. Current status: `docs/PROGRESS.md`.
Stack decisions: `docs/adr/0001-technology-stack.md`.

## Working agreement with the owner

* Build **one phase at a time**. Test, commit, then **stop and wait for approval**.
* Never fake a feature or use dummy data. Pages for unbuilt features are not shown.
* Never delete user data without asking. Removing a module keeps data; a purge
  asks for typed confirmation.
* Keep this file and `docs/PROGRESS.md` updated at the end of every phase.
* The owner deploys and tests on their own server and does not give the sandbox
  access to it. Instructions must therefore be exact and copy-pasteable, and
  anything not verified in the sandbox must be listed as unverified in
  `docs/PROGRESS.md`.

## Hard architecture rule

Logging and Monitoring are independent per host (PDF section 15). Separate
stores (Loki, Prometheus), separate agent services, separate Compose projects,
separate permissions. They are correlated only by `host_id`, `environment`,
`application`, `service` and time.

## Layout

```
bin/obsctl            CLI entrypoint (bash); dispatches `obsctl <module> <verb>`
lib/                  obsctl shell libraries (common, secrets, compose, modules/*)
deploy/<module>/      Compose file, templates, systemd units per module
backend/              FastAPI app (app/), Alembic (alembic/), tests (tests/)
frontend/             React + TypeScript + Vite app
tests/obsctl/         bats tests for the CLI (fake docker shim)
docs/                 install/agent/user/troubleshooting guides, ADRs, PROGRESS.md
```

## Conventions

* Python 3.12 compatible, sync SQLAlchemy 2.0, Pydantic v2, ruff for lint.
* Every mutating endpoint calls `audit.record(...)` (success, failure and denied).
* Permissions live in `backend/app/rbac/permissions.py`. New permission = new
  Alembic migration that also grants it to the right built-in roles.
* Secrets are files (`*_FILE` env convention), never env values, never in git.
* Shell: `set -Eeuo pipefail`, shellcheck clean, no `eval`, quote everything.
* Commit messages end with the attribution lines the harness provides.

## How to run the checks

```
cd backend && python -m pytest -q            # needs PostgreSQL 16 (see tests/conftest.py)
cd backend && ruff check .
cd frontend && npm ci && npm run lint && npm test && npm run build
shellcheck bin/obsctl lib/*.sh lib/modules/*.sh deploy/*/*.sh
bats tests/obsctl
docker compose -f deploy/core/docker-compose.yml config   # syntax check only
```

## Sandbox limits (as of Phase 1)

The build sandbox cannot reach PyPI, npm, Docker registries or the owner's
server (never work around the egress block). Backend and frontend were only
syntax-checked in Phase 1; obsctl is fully tested with a fake docker. Compose
stacks and Dockerfiles are verified by the owner on their server using
`docs/install-guide.md` ("Verify the install") and the checklist in
`docs/PROGRESS.md`. First thing in the next session: ask for the owner's test
output, fix failures, then continue with the next phase only after approval.
If the registries become reachable, run the full check list above first.

## Pointers

* Dockerfiles work with or without lock files; `scripts/lock-deps.sh` creates them.
* Core module code: `lib/modules/core.sh`, `deploy/core/`. New modules copy that pattern.
* Tests: `tests/obsctl` (bash, bats), `backend/tests` (pytest, needs `OBS_TEST_ADMIN_URL`),
  `frontend/src/**/*.test.ts(x)` (vitest).
