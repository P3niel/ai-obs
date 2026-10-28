# Security Policy

## Reporting a Vulnerability

Report suspected vulnerabilities through GitHub's private vulnerability
reporting on this repository (Security tab → "Report a vulnerability"),
rather than opening a public issue or pull request. If that option is not
available, contact the repository owner (`P3niel`) directly through GitHub.

Please include:

- the affected file(s)
- steps to reproduce
- the potential impact

You should expect an initial response within 5 business days. This is a
small, actively-developed repository maintained by one primary owner —
there is no dedicated security team, so timelines are best-effort rather
than contractual.

## Scope

This repository ships a prototype: an in-memory backend (`backend/app/`)
with one pinned external runtime dependency (`rfc8785`), and a static, read-only run
dashboard (`frontend/dashboard.html`) reading embedded example data. There
is no deployed production service, no user-facing authentication, and no
live database. Most classic web-application vulnerability classes (session
hijacking, SQL injection, XSS against real user data) do not yet have a
surface to apply to. Relevant scope today is narrower:

- the CI pipeline (`.github/workflows/`) and its dependencies
- dependency vulnerabilities in `backend/requirements-dev.txt`
- the alert-dispatch webhook path (`backend/app/alert_dispatch.py`), which
  does make outbound HTTP calls to caller-configured Slack/Discord URLs

## Secret Handling

- This repository has no committed secrets. `backend/app/alert_dispatch.py`
  reads webhook URLs from environment variables
  (`AI_OBS_SLACK_WEBHOOK_URL`, `AI_OBS_DISCORD_WEBHOOK_URL`) — see
  [docs/api.md](docs/api.md). Provider secrets must stay outside
  repository-managed files.

## Dependencies

Dependency vulnerabilities are covered by GitHub Dependabot alerts. Treat a
Dependabot PR like any other change requiring the same review process, not
an auto-merge.

## Supported Versions

This project does not yet maintain multiple released versions. Fixes apply
to `main` only.
