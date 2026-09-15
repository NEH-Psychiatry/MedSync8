---
applyTo: "**/*.py"
---

# Python Rules

- Target Python 3.11+. Full type hints on public functions, methods, and module-level constants. `from __future__ import annotations` where the module already uses it (the backend does).
- No Python linter or formatter is configured in this repository. Match the surrounding code's style; do not claim Ruff or mypy results.
- FastAPI services (`backend/`): Pydantic models for all request/response bodies; explicit status codes; no bare `except`; structured logging with no PHI, secrets, or member identifiers in log lines.
- Audit logging follows the hash-only pattern in `backend/audit.py` — log content hashes and metadata, never payloads that could contain PHI. Do not weaken or bypass it.
- Auth (`backend/auth.py`): Cloudflare Access JWT verification stays mandatory in production paths; any dev-mode bypass must be explicit, env-gated, and off by default.
- Environment variable contracts (`ANTHROPIC_MODEL`, `EMBED_BACKEND`, and the rest of `.env.example`) are public API — do not rename or repurpose them without the task requiring it.
- Retriever and embedder changes must keep the stub-embedder test path working so `backend/tests` runs without model downloads or network access.
- Tests: `pytest` for `backend/tests`, `unittest` for legacy `/tests`. Synthetic fixtures only, no network calls, deterministic seeds for anything random.
- Dependency changes require a one-line justification in the PR and an updated requirements entry with a version bound — never a loose unpinned addition to production requirements. `backend/requirements-test.txt` intentionally excludes torch/sentence-transformers; keep it that way.
- Docstrings on public modules and functions: one-line summary, then args/returns when non-obvious. No docstring theater on trivial private helpers.
