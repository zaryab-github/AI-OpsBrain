# ADR-0001: Technology stack and module architecture

Status: accepted (Phase 0 plan, approved by the owner on 2026-10-29)

## Context

`docs/AI_Centralized_Observability_Platform_Architecture.pdf` describes a
platform with centralized logging, monitoring, alerting, reporting, AIOps and
controlled remediation. The hard architectural rule is PDF section 15:
**Logging and Monitoring are independent per host**. A host can have logging
only, monitoring only, or both, and each can be enabled, disabled or removed
without touching the other.

Decided scale: single Linux VM, up to ~50 hosts, <50 GB logs/day.
Decided TLS: Caddy internal CA on a private hostname (public ACME and
bring-your-own certificate are also supported by the installer).
Decided notification channel for the first release: email (SMTP).
Decided AI providers: all of Ollama, Anthropic API and any OpenAI-compatible API.

## Decision

| Concern | Choice |
|---|---|
| Log store | Grafana Loki (single binary mode) |
| Metric store | Prometheus with the remote-write receiver enabled |
| Host agent | Grafana Alloy, installed as **two separate services** (`obs-agent-logging`, `obs-agent-monitoring`), each with its own config, credential, port and uninstall path |
| Control plane | Python 3.12, FastAPI, SQLAlchemy 2 (sync), Alembic, PostgreSQL 16 |
| Alert engine | Own implementation inside the backend (evaluates LogQL/PromQL on a schedule, owns lifecycle: acknowledge, resolve, silence, assign, escalate) |
| Frontend | React, TypeScript, Vite, Tailwind CSS, TanStack Query, ECharts |
| AI layer | Provider-agnostic adapter; statistical anomaly detection; LLM only sees evidence fetched by the platform |
| Automation | n8n as the only executor (HMAC-signed webhooks); approval and risk policy enforced by the backend |
| Edge / TLS | Caddy |
| Packaging | One Docker Compose project per module, driven by one CLI (`obsctl`) |
| Auth | Argon2id, TOTP MFA, short-lived JWT access tokens, rotating refresh tokens, RBAC permission matrix |
| Audit | Append-only, HMAC hash-chained table protected by DB triggers |

## Why

* **Independence is structural, not a flag.** Loki, Prometheus and the two
  agent services share nothing but the host id. Removing the logging module
  leaves the monitoring module running, and the reverse.
* **Python backend** because the AI layer (baselines, correlation, report
  generation) is Python-native and the operator audience maintains Python well.
* **Sync SQLAlchemy** keeps transaction handling simple and correct; blocking DB
  calls run in FastAPI's thread pool. Calls to Loki/Prometheus/LLMs use async
  `httpx` and never hold a DB connection while waiting.
* **Own alert engine** because the PDF's alert actions (acknowledge, assign,
  escalate, investigate with AI) and threshold profiles are application
  concepts that Alertmanager does not model. Alertmanager remains an optional
  integration.
* **Statistical anomaly detection** is deterministic, explainable and cheap.
  The LLM explains and correlates; it does not decide whether a metric is
  anomalous.
* **n8n as sole executor** means the platform never runs shell commands itself;
  every remediation is an auditable workflow execution gated by our approval
  policy.
* **Compose per module** gives each module its own lifecycle
  (install/status/upgrade/backup/restore/remove) and lets "remove" keep data by
  default.

## Consequences

* Single-node Loki/Prometheus bound the supported scale (see the decided
  scale). Larger scale needs a new ADR (clustered stores).
* Images are built on the target server from this repository
  (`obsctl <module> install` / `upgrade`), so the server needs access to its
  base-image registries during install and upgrade.
* The backend is a single replica in v1. Per-IP login rate limiting is
  in-process; a multi-replica deployment must move it to the database.

## Rules every phase must follow

1. No fake features or dummy data. UI pages for unbuilt features are not shown.
2. No default credentials; every secret is generated at install.
3. Every state change is written to the audit log.
4. Every module supports `install | status | upgrade | backup | restore | remove`;
   `remove` keeps data; `remove --purge` requires typed confirmation.
5. Each phase ships its docs (install, agent, user, troubleshooting) and tests.
