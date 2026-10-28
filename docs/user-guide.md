# User guide

This guide grows with each phase. It currently covers signing in, your account, and the Administration area.

## Signing in

1. Open the platform address (for example `https://opsbrain.corp.example`).
2. Enter your username (or email) and password.
3. If two-factor authentication is on for your account, enter the 6-digit code from your authenticator app.
4. If an administrator created your account, you are asked to choose your own password first.
5. If your role requires two-factor authentication and you have not set it up, the platform shows a QR code: scan it
   with Microsoft Authenticator, Google Authenticator, 1Password or similar, then enter the code.

After five wrong passwords or codes in a row the account locks for 15 minutes (both configurable). An administrator
can unlock it sooner. Sessions end after 30 minutes of inactivity or 12 hours in total (configurable).

## My account

Open the user menu (top right) → **My account**:

- **Password** — change it. All your other sessions are signed out.
- **Two-factor authentication** — set up or turn off (turning off is not possible when your role requires it).
- **Active sessions** — see where you are signed in and sign out other sessions.

## Navigation and workspaces

The left menu follows the platform structure: Overview, Host Management, Logging, Monitoring, AI / AIOps,
Automation, Incidents, Reports, Retention & Archive, Integrations and Administration. You only see the entries
your role allows.

Logging and Monitoring are separate workspaces. The ↗ icon next to each opens it in its own browser window
containing only that workspace's menu — useful on a second screen.

Modules that are not installed show **off** in the menu. Pages that are not built yet say so; they never show
sample data.

## Overview

Shows which platform modules are installed and, for users who can view system settings, the platform's own
health. Infrastructure, alert and AI summaries are added here as those modules arrive.

## Administration

### Users (permission: `users.manage`)

- **Add user** — enter username, name, email and roles. The platform generates a temporary password and shows it
  once; give it to the person through a secure channel. They must change it at first sign-in.
- **Edit** — change name, email or roles.
- **Reset password** — issues a new temporary password and signs the user out everywhere.
- **Reset 2FA** — removes the user's authenticator; they set it up again at next sign-in if required.
- **Unlock** — clears a lockout.
- **Deactivate / Reactivate** — deactivated users cannot sign in; their history stays. Accounts are never deleted,
  so the audit trail always resolves to a person.

You cannot deactivate yourself, and the last active Admin cannot be demoted or deactivated.

### Roles & RBAC (permission: `users.manage`)

A matrix of permissions (rows) and roles (columns). Tick or untick, then **Save changes**.

| Role | Intended for |
|---|---|
| Admin | Everything, always (cannot be edited) |
| DevOps | Operating the platform: hosts, rules, thresholds, automation, integrations, retention |
| NOC | Watching and responding: alerts, incidents, AI investigations |
| Developer | Reading logs and metrics, running AI log analysis |
| Viewer | Read-only operational data |
| Auditor | Read-only everything, including the audit log |

**New role** creates a custom role. Built-in roles cannot be deleted; custom roles can once no user has them.

### Audit Logs (permission: `audit.view`)

Every sign-in (successful or not), permission denial and change, with: time, user, IP address, action, resource,
host, old value, new value, result and detail. Click a row to see old and new values.

- Filter by user, action prefix (e.g. `user.`), resource type, result, time range or free text.
- **Export CSV** downloads the filtered entries (the export itself is audited).
- **Verify integrity** recomputes the hash chain. "Hash chain intact" means no entry was altered, removed or
  reordered. The worker also verifies hourly and reports the result under platform health.

Audit entries cannot be edited or deleted through the platform or by its database account.

### System Settings (permission: `settings.view` to see, `settings.manage` to change)

| Setting | Default |
|---|---|
| Platform name | AI-OpsBrain |
| Two-factor authentication required for | Users who can manage users or settings |
| Minimum password length | 12 |
| Session idle timeout | 30 minutes |
| Maximum session length | 12 hours |
| Failed logins before lockout | 5 |
| Lockout duration | 15 minutes |

The **Platform health** panel shows the API, database, queue, background worker, audit integrity, last backup and
TLS certificate, each with ok / warning / critical.
