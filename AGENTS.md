# AGENTS.md — MedSync8 Agent Guide

Applies to any coding agent operating in this repository (GitHub Copilot coding agent, Copilot code review, Claude Code, Codex, or equivalent). `.github/copilot-instructions.md` is the governance baseline; this file adds operational specifics. Path-scoped `.github/instructions/*.instructions.md` files win for their paths.

## Setup and validation

- **Backend** (Python 3.11+): `pip install -r backend/requirements-test.txt`, then `python -m pytest backend/tests -q`. Tests stub the embedder — no model downloads, no network. Full runtime deps are in `backend/requirements.txt` (torch, sentence-transformers); the Docker build installs those.
- **Frontend** (Node 20): `cd frontend && npm ci`, then `npm run lint`, `npm run test`, `npm run build`.
- **Legacy calculator**: `pip install -r requirements.txt`, then `python -m unittest discover tests -v`.
- No Python linter or type checker is configured. Never claim Ruff or mypy validation.
- If a command cannot run in your environment, state that explicitly in the PR description. Never claim validation that did not occur.

## Task execution

1. Read the issue or task acceptance criteria in full before editing.
2. Locate the smallest set of files that satisfies the task. Do not refactor beyond scope.
3. Preserve public APIs, request/response schemas, environment variable names, CLI flags, filenames, and workflow names unless the task requires the change.
4. Write or update tests alongside the change (backend: `backend/tests/`; frontend: `frontend/src/__tests__/`; legacy: `tests/`).
5. Run lint and tests. Record results.
6. Update README, RUNBOOK, or backend/corpus READMEs when user-facing or operational behavior changes.
7. Open a PR that passes the quality gate in `.github/copilot-instructions.md`.

## Hard boundaries

- No PHI, patient identifiers, dates of service, 42 CFR Part 2 records, payer/member identifiers, privileged legal strategy, secrets, or real production data — anywhere, including tests, fixtures, comments, and commit messages.
- Do not weaken the hash-only audit pattern in `backend/audit.py`: hashes and metadata only, never message payloads.
- Do not bypass or relax Cloudflare Access verification in `backend/auth.py` outside an explicit auth task.
- The corpus under `/corpus` contains public federal regulation text only. Never add clinical excerpts, patient material, or licensed content to it.
- No new unpinned GitHub Actions. Pin new or changed actions to full-length commit SHAs.
- No `pull_request_target` without explicit human approval in the task.
- No force pushes to protected branches. No history rewrites.
- Do not modify `.github/copilot-instructions.md`, this file, or any `.instructions.md` file unless the task is specifically an instructions update.

## When blocked

Stop and report — with the exact blocker — rather than guessing, when: sources conflict per the precedence ladder; a required credential or service (Anthropic, OpenAI, Cloudflare, Stripe, Supabase) is unavailable; acceptance criteria are ambiguous on a clinical, legal, or compliance point; or a change would touch PHI-adjacent code paths (audit logging, auth, chat payload handling) without a stated test strategy.
