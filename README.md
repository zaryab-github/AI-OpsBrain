# AI Centralized Observability Platform

Self-hosted logging, monitoring, alerting, incident management and AI-assisted operations for Linux and Windows
hosts. Logging and Monitoring are independent per host.

* Scope: `docs/AI_Centralized_Observability_Platform_Architecture.pdf`
* Status and owner checklist: `docs/PROGRESS.md`
* Install: `docs/install-guide.md` | Use: `docs/user-guide.md` | Fix problems: `docs/troubleshooting.md`
* Stack decisions: `docs/adr/0001-technology-stack.md`

```bash
sudo git clone <repo> /opt/obs && sudo ln -sf /opt/obs/bin/obsctl /usr/local/bin/obsctl
sudo obsctl core install
sudo obsctl core status
```

Built so far: **Phase 1 (Core)**. Later modules install the same way (`obsctl logging install`, ...).
