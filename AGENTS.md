# AGENTS.md — MedSync8 Repository Agent Guide

Applies to any coding agent operating in this repository (GitHub Copilot coding agent, Copilot code review, Claude Code, Codex, or equivalent). `.github/copilot-instructions.md` is the governance baseline; this file adds operational specifics. Path-scoped `.github/instructions/*.instructions.md` files (actions, python, frontend, docs, tests) win for their paths. `CLAUDE.md` carries the detailed architecture notes.

## Setup and validation

- **Python** (3.11+): `pip install -r backend/requirements-test.txt` (fast, no torch), then `python -m pytest backend/tests tests -q`. Backend tests use `StubEmbedder` and `StubAnthropic` from `backend/tests/conftest.py` — no model downloads, no network; keep it that way. Full runtime deps are in `backend/requirements.txt`; the Docker build installs those.
- **Workbench** (Node 20): `npm ci`, `npm run build`. Dev: `npm run dev` (Vite 5173 + Express 3001; requires `ANTHROPIC_API_KEY` in `.env`).
- **Frontend** (Node 20): `cd frontend && npm ci`, then `npm run lint`, `npm test`, `npm run build`.
- **Legacy calculator**: `pip install -r requirements.txt`, then `python -m unittest discover tests -v`.
- No Python linter or type checker is configured. Never claim Ruff or mypy validation.
- If a command cannot run in your environment, state that explicitly in the PR description. Never claim validation that did not occur.

## Task execution

1. Read the issue or task acceptance criteria in full before editing.
2. Locate the smallest set of files that satisfies the task. Do not refactor beyond scope.
3. Preserve public APIs, request/response schemas, environment variable names, CLI flags, filenames, and workflow names unless the task requires the change.
4. Adding a tool ID requires updating **all five places**: `src/constants.js`, `server.js`, `backend/prompts.py`, the `Literal` in `backend/server.py`, and `frontend/src/prompts.js` (`backend/tests/test_prompt_tool_sync.py` guards the last).
5. Changes to billing logic in `scripts/cocm_time_tracker.py` must preserve CMS thresholds (99492 ≥36, 99493 ≥31, 99494 at target+16, G2214 ≥30, 99484 ≥20), rule fields (`status`, `mirror_of`, `requires_any_of`, `exclusive_with`, `payers`), disclaimers, and rate-confidence labels with `rate_source`; add rules as data, never as prose; boundary-test the edges after any change (the `billing-auditor` agent in `.claude/agents/` does this) and re-sync the plugin copy (`tests/test_plugin_sync.py`).
6. Write or update tests alongside the change (backend: `backend/tests/`; root scripts and MCP: `tests/`; frontend: `frontend/src/__tests__/`; legacy: `tests/`). Run lint and tests; record results.
7. Update README, RUNBOOK, `docs/USER_GUIDE.md`, `CLAUDE.md`, or `CHANGELOG.md` when user-facing or operational behavior changes.
8. Open a PR that passes the quality gate in `.github/copilot-instructions.md`.

## Hard boundaries

- No PHI, patient identifiers, dates of service, 42 CFR Part 2 records, payer/member identifiers, privileged legal strategy, secrets, or real production data — anywhere, including tests, fixtures, `corpus/`, comments, and commit messages.
- Do not weaken the hash-only audit pattern in `backend/audit.py`: hashes and metadata only, never message payloads; never weaken `hash_query` salting.
- Do not bypass or relax Cloudflare Access verification in `backend/auth.py` outside an explicit auth task; the admin audit gate (`require_admin`, `AUDIT_ADMIN_EMAILS`) fails shut and must stay that way. `/api/health` must not disclose internals or advertise that auth is disabled.
- `corpus/` contains public federal regulation text only. Never add clinical excerpts, patient material, or licensed content to it.
- Never remove decision-support disclaimers or source-confidence labels from clinical or billing scripts.
- Every outbound backend relay is time-bounded (`ANTHROPIC_TIMEOUT_SECONDS`, `OPENAI_TIMEOUT_SECONDS`, JWKS 5 s, Teams 15 s); do not add an unbounded external call.
- No new unpinned GitHub Actions. Pin to full-length commit SHAs.
- No `pull_request_target` without explicit human approval in the task.
- No force pushes to protected branches. No history rewrites.
- Do not modify `.github/copilot-instructions.md`, this file, or any `.instructions.md` file unless the task is specifically an instructions update.

## When blocked

Stop and report — with the exact blocker — rather than guessing, when: sources conflict per the precedence ladder; a required credential or service (Anthropic, OpenAI, Cloudflare, Azure, Stripe, Supabase, Teams) is unavailable; acceptance criteria are ambiguous on a clinical, legal, billing, or compliance point; a billing threshold or payer rate cannot be verified against a primary source; or a change would touch PHI-adjacent code paths (`corpus/`, `backend/audit.py`, `backend/auth.py`, `backend/retriever.py`, chat payload handling) without a stated test strategy.
