# User guide (Phase 1: Core)

Phase 1 delivers sign-in, user and role administration, the audit log, system settings and
platform health. Pages for hosts, logs, metrics, alerts and so on appear in the left menu
only when those modules are built; nothing is shown for features that do not exist yet.

## Sign in

Open the URL printed by the installer. Enter username and password. If MFA is enabled you
are asked for the 6-digit code from your authenticator app (or a recovery code, once each).

* **Locked out?** After too many wrong attempts the account is locked for a while
  (Administration > System Settings > Security). An administrator can unlock it on the Users
  page, or on the server: `sudo obsctl core admin unlock --user NAME`.
* The sign-in error message is deliberately the same for a wrong username and a wrong password.

## First sign-in and your account

* A new or reset password must be changed on first sign-in (minimum 12 characters).
* **Profile > Two-factor authentication**: scan the QR code, enter a code to enable. You get
  recovery codes **once** - store them somewhere safe.
* **Profile > Sessions** lists every signed-in device; revoke any you do not recognise.
  Changing your password or resetting MFA signs out your other sessions.

## Administration (needs the matching permission)

### Users
Create users, assign a role, disable/enable, unlock, reset a password (the user must change
it at next sign-in), and reset MFA. Users are **deactivated, never deleted**, so the audit trail
stays meaningful. The last active Admin cannot be disabled or demoted.

### Roles & RBAC
Built-in roles: **Admin** (everything), **DevOps**, **NOC**, **Developer**, **Viewer**,
**Auditor**. Built-in roles are fixed. Create custom roles by choosing permissions from the
catalogue. A role that still has users cannot be deleted.

### Audit Logs
Every change - and every failed or denied attempt - is recorded with who, what, when, old and
new value, and result. Filter by user, action, result and date. **Export CSV** downloads the
current filter. The log is append-only and hash-chained; **Verify integrity** (or
`sudo obsctl core verify-audit`) detects tampering. Secrets are never written to the log.

### System Settings
Instance name, "require MFA for everyone", token and session lifetimes, password minimum,
lockout rules, and the optional external heartbeat URL. Each change is audited.

### System health
Shows self-monitoring checks: database, migrations, audit-chain integrity, worker heartbeat,
and the host watchdog (disk, certificate expiry, containers, backup age). Set a heartbeat URL
(for example a Healthchecks.io-style endpoint) so an *external* service alerts you if the whole
platform goes silent.

## Command line (server)

```bash
sudo obsctl core status                 # is everything up?
sudo obsctl core logs -f api            # follow a service log
sudo obsctl core admin reset-password --user NAME --generate-password
sudo obsctl core admin disable-mfa --user NAME
```
