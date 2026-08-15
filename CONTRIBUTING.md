# Contributing

This is a solo-maintained showcase/portfolio project, not a project actively
seeking feature contributions. That said, bug reports, doc corrections, and
small fixes are welcome.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r backend/requirements-dev.txt
```

`backend/requirements.txt` is intentionally empty — the runtime code has no
external dependencies. `requirements-dev.txt` installs the lint/type-check/
test/security-scan toolchain.

## Running the checks

From the repository root:

```bash
.venv/bin/flake8 backend
.venv/bin/mypy backend/app backend/run_demo.py
cd backend && ../.venv/bin/pytest -q && cd ..
.venv/bin/bandit -r backend
```

All four run in CI on every pull request (see `.github/workflows/ci.yml`).

## Making a change

1. Open an issue first for anything beyond a small fix, so we don't cross
   wires on direction.
2. Keep changes small and focused — one logical change per pull request.
3. Add or update tests for any behavior change.
4. Make sure the checks above pass locally before opening a PR.

## Scope

Read [docs/architecture.md](docs/architecture.md) and
[README.md](README.md)'s Current Status section before proposing new
capabilities — several things that look like obvious next steps (live
dashboard feed, HTTP API, cost/token metrics) are deliberately out of scope
for this slice and tracked as roadmap items, not gaps to silently fill in.
