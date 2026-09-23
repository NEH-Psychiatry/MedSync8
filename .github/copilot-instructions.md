# MedSync8 Copilot Instructions

Version 1.0.1 — 2026-09-23.

This repository uses NEH enterprise AI governance. Follow these instructions for Copilot Chat, Copilot coding agent, Copilot code review, and repository-scoped AI assistance.

## Repository mission

MedSync8 supports NEH telepsychiatry work: a React chat UI backed by a FastAPI RAG service that proxies Anthropic and cites a local regulatory corpus, plus a legacy Streamlit medication sync calculator. Preserve clinical, legal, regulatory, payer, billing, operational, and technical meaning exactly.

## Repository context

Two application tracks:

- **Telepsychiatry assistant (current stack)**
  - `/backend` — Python 3.11+, FastAPI, Pydantic v2, local sentence-transformers embeddings (OpenAI optional), Anthropic proxy, Cloudflare Access JWT auth, hash-only audit logging.
  - `/frontend` — React 19 + Vite, ESLint, Vitest; deployed to Cloudflare Pages.
  - `/corpus` — local RAG source documents (public federal regulation text only).
- **Legacy Streamlit calculator** — `/med_sync_app_with_stripe.py`, `/sync_calculator.py`, tests in `/tests`.

Build, lint, and test commands:

- Backend tests: `python -m pytest backend/tests -q` (uses `backend/requirements-test.txt`; tests stub the embedder — no model downloads, no network).
- Frontend: `cd frontend && npm ci`, then `npm run lint`, `npm run test`, `npm run build`.
- Legacy calculator tests: `python -m unittest discover tests -v`.
- No Python linter is configured yet. Do not claim Ruff or mypy results; if one is added, it governs from that point.
- File naming for user-facing artifacts: hyphens, never underscores, per NEH file governance.

## Working rules

- Read this file, the matching `.github/instructions/*.instructions.md` file, `AGENTS.md`, task acceptance criteria, and nearby code before making changes.
- Make the smallest correct change. Avoid unrelated refactors.
- Prefer explicit, typed, tested, maintainable code.
- Preserve public APIs, request/response schemas, environment variable names, filenames, workflow names, and deployment behavior unless the task explicitly requires a change.
- Add or update tests for behavior changes.
- Update README/RUNBOOK/docs when user-facing or operational behavior changes.
- Do not fabricate files, commands, test results, credentials, policy claims, citations, or implementation status.
- State validation performed. If tests cannot be run, explain exactly why.

## Source precedence

Use the highest-authority available source:

1. Current user request and acceptance criteria
2. Repository files and current code
3. Matching `.github/instructions/*.instructions.md` (path-scoped rules win for their paths)
4. `.github/copilot-instructions.md` (this file — repository-wide baseline)
5. `AGENTS.md`
6. Current issue, PR, or release plan
7. Historical docs or comments

If sources conflict, stop and call out the conflict before making a risky change.

## Security and privacy

Never commit or expose:

- PHI, patient identifiers, raw clinical excerpts, dates of service
- 42 CFR Part 2 substance use disorder records or references to them
- payer/member identifiers
- privileged legal strategy
- secrets, tokens, private keys, credentials (Anthropic, OpenAI, Cloudflare, Stripe, Supabase)
- sensitive source paths or private infrastructure details
- real production data in tests or fixtures

Use synthetic examples only. Keep logs and errors free of secrets and sensitive data. The backend's audit log is hash-only by design — log content hashes and metadata, never message payloads; do not weaken this pattern.

## GitHub Actions

For workflows:

- Set explicit least-privilege `permissions` at workflow or job level.
- Avoid `pull_request_target` unless explicitly required and reviewed.
- Never check out or execute untrusted PR code in a privileged context.
- Do not introduce unpinned actions; pin new or changed actions to full-length commit SHAs.
- Use environment protection and required reviewers for deployment secrets (Cloudflare Pages deploy, PyPI publish).
- Prefer OIDC over long-lived cloud credentials.

## Commits, branches, and PRs

- Branch names: `feat/`, `fix/`, `docs/`, `ci/`, `chore/` prefix plus a short kebab-case slug.
- Commit messages: imperative mood, subject 72 characters or fewer, body explains why.
- One logical change per PR. Link the issue. Label breaking or risky changes.

## Copilot code review priorities

Review in this order:

1. Security and privacy violations per this file — PHI or secrets in code, tests, fixtures, or logs; auth bypasses in `backend/auth.py`; weakening of hash-only audit logging.
2. Correctness and missing tests — backend request validation, retriever behavior, prompt/tool sync, frontend chat state.
3. API/schema/workflow stability — request/response models, environment variable contracts, CI and deploy workflow behavior.
4. Maintainability and typing.
5. Style. Do not request purely stylistic churn that ESLint already governs in `/frontend`; there is no Python formatter configured, so flag only genuine readability problems in Python.

## Pull request quality gate

Before proposing or finalizing a PR:

- Build passes or limitation stated
- Tests pass or limitation stated
- Lint checks pass (frontend ESLint) or limitation stated
- Security/privacy review completed
- Docs updated when needed
- Risky or breaking changes clearly labeled
- Rollback or mitigation noted for operational changes (deploys, Docker, Fly, Cloudflare)

## Changelog

- 1.0.1 (2026-09-23): Corrected the frontend stack from React 18 to React 19 here and in `.github/instructions/frontend.instructions.md`; `frontend/package.json` pins `react@^19.2.0`. Reported by Copilot code review on PR #10.
- 1.0.0 (2026-08-16): Initial instruction set for MedSync8. Root file plus `AGENTS.md` and path-scoped rules for workflows, Python, frontend, docs, and tests. Skills rules omitted — this repository contains no `.skill` packages or SKILL.md files.
