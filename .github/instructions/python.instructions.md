---
applyTo: "**/*.py"
---

# Python Rules

- Target Python 3.11+. Full type hints on public functions, methods, and module-level constants. `from __future__ import annotations` where the module already uses it (`backend/`, `scripts/`, `mcp/` do).
- No Python linter or formatter is configured in this repository. Match the surrounding code's style; do not claim Ruff or mypy results.
- FastAPI services (`backend/server.py`): Pydantic models for all request/response bodies; explicit status codes; no bare `except`; structured logging with no PHI, secrets, or member identifiers in log lines. `/api/health` is unauthenticated and must not expose model, corpus, embedder, auth-disabled, or default-salt state.
- Audit logging follows the hash-only pattern (`backend/audit.py`) — log salted content hashes and metadata, never payloads that could contain PHI. Do not weaken or bypass it; do not change the salting scheme without an instructions-level task.
- Auth (`backend/auth.py`): Cloudflare Access JWT verification stays mandatory in production paths; any dev-mode bypass must be explicit, env-gated, and off by default. The admin gate (`require_admin`) fails shut when `AUDIT_ADMIN_EMAILS` is unset.
- Every outbound call carries an explicit timeout (Anthropic and OpenAI clients via `ANTHROPIC_TIMEOUT_SECONDS` / `OPENAI_TIMEOUT_SECONDS`, JWKS fetch 5 s, Teams webhook 15 s). Never add an unbounded external call.
- Environment variable contracts (`ANTHROPIC_MODEL`, `EMBED_BACKEND`, `AUDIT_SALT`, `CF_ACCESS_*`, `AUDIT_ADMIN_EMAILS`, and the rest of the `.env.example` files) are public API — do not rename or repurpose them without the task requiring it.
- Imports inside the `backend/` package use relative form (`from .audit import ChatAuditContext`).
- Retriever and embedder changes must keep the stub-embedder test path working so `backend/tests` runs without model downloads or network access.
- Billing scripts (`scripts/cocm_time_tracker.py`): CMS thresholds, rule fields (`status`, `mirror_of`, `requires_any_of`, `exclusive_with`, `payers`), disclaimers, and rate-confidence labels with `rate_source` are load-bearing — never alter a threshold without citing the governing CMS source in the PR, never present an estimated or crosswalk-derived rate as verified, and add a rule by setting a field, never by writing a sentence in `notes`. Boundary-test edges (35/36, 30/31, target+15/+16, 19/20) after any eligibility change and re-sync the plugin's vendored copy.
- Alert scripts (`scripts/credentialing_alert.py`): outbound HTTP always carries a timeout; delivery failure must surface in the exit code; no PHI in card payloads — aggregate risk metadata only; time-dependent logic takes `today: date` as a parameter.
- Tests: `pytest` for `backend/tests` and root `tests/`, `unittest` for the legacy calculator. Synthetic fixtures only, no network calls (use `StubEmbedder`/`StubAnthropic` from `backend/tests/conftest.py`), deterministic seeds for anything random.
- Dependency changes require a one-line justification in the PR and an updated requirements entry with a version bound — never a loose unpinned addition to production requirements. `backend/requirements-test.txt` intentionally excludes torch/sentence-transformers; keep it that way.
- Docstrings on public modules and functions: one-line summary, then args/returns when non-obvious. No docstring theater on trivial private helpers.
