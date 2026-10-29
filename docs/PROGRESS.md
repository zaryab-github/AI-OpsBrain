# Progress

Source of scope: `docs/AI_Centralized_Observability_Platform_Architecture.pdf`.
Rules: one phase at a time; test, commit, stop, wait for owner approval. No fake features, no dummy data,
never delete data without asking.

## Phase plan

| # | Phase | Status |
|---|---|---|
| 1 | Foundation and Core (repo, obsctl, TLS proxy, Postgres, auth + MFA, users, RBAC, audit log, settings, UI shell, self-monitoring, core lifecycle commands) | **Built - awaiting owner verification and approval** |
| 2 | Host Management and Agents (Hosts, Add Host, Groups, Linux/Windows agents, per-capability enable/disable/remove) | not started |
| 3 | Logging module (Loki, sources, dashboard, explorer, live logs, patterns, retention) | not started |
| 4 | Monitoring module (Prometheus, infra/app/service/db monitoring, metrics explorer) | not started |
| 5 | Alerting (log rules, thresholds/profiles, monitoring alerts, lifecycle, e-mail) | not started |
| 6 | Incidents and Reporting | not started |
| 7 | AI / AIOps | not started |
| 8 | Automation (n8n) | not started |
| 9 | Retention/Archive, Integrations, hardening | not started |

## Phase 1 - what exists

* `obsctl core install | status | upgrade | backup | restore | remove [--purge] | reconfigure | logs | watchdog | admin | verify-audit | export-ca | backup-key | timers`
* Compose stack: postgres, migrate, api, worker, proxy (Caddy, TLS internal/acme/custom).
* Backend: login, TOTP MFA + recovery codes, refresh-token rotation with reuse detection, lockout, forced password change,
  users, roles/RBAC (6 built-in + custom), hash-chained append-only audit log with CSV export and verify, typed system settings,
  self-monitoring (db, migrations, audit chain, worker heartbeat, host watchdog), Prometheus `/metrics` (token protected, not proxied).
* Frontend: Login, Profile (password, MFA, sessions), Overview, Users, Roles & RBAC, Audit Logs, System Settings + System health.
  Menu shows only pages that exist.
* Docs: install guide, user guide, troubleshooting. CI workflow in `.github/workflows/obs-ci.yml`.

## Phase 1 - verification status (be honest)

The build sandbox could not reach PyPI, npm or Docker registries, and the owner does not give it access to their server.

| Area | Verified in sandbox | How |
|---|---|---|
| obsctl (bash) | **Yes** | shellcheck clean; 46 bats tests pass using a fake `docker`/`curl` |
| Compose file | Syntax only | `docker compose config -q` |
| Backend Python | **Syntax only** | `python -m compileall`. **Never imported or run.** pytest and ruff were NOT run |
| Frontend TypeScript | **Syntax only** | tsc parse check. **Never installed, type-checked, linted, built or run**; vitest tests written but NOT run |
| Dockerfiles / real stack start | **No** | needs registries |
| Caddyfile with real Caddy | **No** | `caddy validate` not available |

Expect small defects in the unrun backend/frontend code. They are likely to be import errors, typing
errors or test failures, which are quick to fix once I see the output.

## Owner checklist for Phase 1 (run on the server; send me any failure output)

1. Follow `docs/install-guide.md` sections 1-5 (install + "Verify the install").
2. Run the test suites (the commands below need Docker only):

```bash
# Backend tests + lint (throw-away Postgres on port 55432)
docker run -d --rm --name obs-test-pg -e POSTGRES_PASSWORD=ci -p 127.0.0.1:55432:5432 postgres:16-alpine
sleep 8
docker run --rm --network host -v "$PWD/backend:/app" -w /app \
  -e OBS_TEST_ADMIN_URL=postgresql+psycopg://postgres:ci@127.0.0.1:55432/postgres \
  python:3.12-slim bash -c "pip install -q -r requirements-dev.txt && ruff check . && python -m pytest -q"
docker stop obs-test-pg

# Frontend: install, lint, test, build (also writes package-lock.json)
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine sh -c "npm install && npm run lint && npm test && npm run build"

# Pin dependencies once everything passes
./scripts/lock-deps.sh
```

3. Manual UI check: sign in, change password, enrol MFA, create a user and a custom role, view the Audit Logs,
   export CSV, run Verify integrity, open System Settings > System health, then `sudo obsctl core backup` and
   `sudo obsctl core restore <file>` on a test system.

## Known limits / decisions

* Rate limiting is in-memory per API process (single VM, one API container). Revisit if scaled out.
* The frontend image build runs `vite build` only; type-checking is done in CI / `npm run build`.
* Dependencies are unpinned until `scripts/lock-deps.sh` is run (Dockerfiles work either way).
* Removing a module never deletes data; purge needs a typed confirmation; backups are never auto-pruned.
* Notification channel for the whole project: e-mail (SMTP) only. AI providers: Ollama, Anthropic, OpenAI-compatible.

## Next (after approval)

Phase 2: Host Management and Agents. Add `hosts`, `host_groups`, `host_capabilities`, enrolment tokens, agent
installers (Linux `.sh`, Windows `.ps1`) that install Alloy as two independent services, `obsctl agent ...` docs,
`docs/agent-guide.md`.
