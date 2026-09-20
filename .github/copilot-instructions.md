# NEH GitHub Enterprise Copilot Instructions — MedSync8

Version 1.2.0 — 2026-09-20. Reconciles two independently authored sets: the NEH template lineage (v1.1.1, 2026-07-23) and the MedSync8 set merged to `main` in PR #10 (v1.0.0, 2026-08-16). Where they differed, the stricter rule was kept.

This repository uses NEH enterprise AI governance. Follow these instructions for Copilot Chat, Copilot coding agent, Copilot code review, and repository-scoped AI assistance.

## Repository mission

MedSync8 supports NEH telepsychiatry work: the Psychiatry AI Workbench (policy, supervision, CME, consultation, documentation drafting), a FastAPI RAG telepsychiatry assistant that proxies Anthropic and cites a local regulatory corpus, billing and credentialing decision-support scripts with an MCP tool layer, and a legacy Streamlit medication sync calculator. Preserve clinical, legal, regulatory, payer, billing, operational, financial, and technical meaning exactly.

## Repository context

Three application tracks plus tooling:

- **Workbench (root)** — `src/` React 18 + Vite, `server.js` Express proxy (rate limiting, sanitization, SSE streaming; port 3001). Not deployed by any workflow.
- **Telepsychiatry assistant (production)** — `frontend/` React + Vite + ESLint + Vitest (Cloudflare Pages; `VITE_API_BASE`), `backend/` Python 3.11+ FastAPI, Pydantic v2, local sentence-transformers embeddings (OpenAI optional), Anthropic proxy, Cloudflare Access JWT auth, hash-only audit logging; deployed to Azure Container Apps (`azure/main.bicep`, Key Vault-backed secrets) or Fly.io. `corpus/` holds public federal regulation text only.
- **Clinical scripts and MCP** — `scripts/cocm_time_tracker.py` is the single source of billing truth (rules are data on `BillingCode`, enforced by `price_claim()`); `mcp/cocm_billing_server.py` exposes it as MCP tools; `plugins/medsync8-billing` vendors both and CI enforces byte-identity. `scripts/credentialing_alert.py` posts Teams alerts. Decision-support only — never remove disclaimers or rate-confidence labels.
- **Legacy calculator** — `med_sync_app_with_stripe.py`, `sync_calculator.py`, tests in `tests/test_sync_calculator.py`.

Build, lint, and test commands (CI runs all three jobs):

- Python: `python -m pytest backend/tests tests -q` (uses `backend/requirements-test.txt`; tests stub the embedder and the Anthropic client — no model downloads, no network).
- Workbench: `npm ci`, `npm run build`.
- Frontend: `cd frontend && npm ci`, then `npm run lint`, `npm test`, `npm run build`.
- Legacy calculator: `python -m unittest discover tests -v`.
- No Python linter or type checker is configured. Do not claim Ruff or mypy results; if one is added, it governs from that point.
- Tool IDs (`policy`, `supervision`, `lecture`, `chat`, `documentation`) are the central organizing concept and are mirrored in **five places** that must stay in sync: `src/constants.js`, `server.js` SYSTEM_PROMPTS, `backend/prompts.py`, the Pydantic `Literal` in `backend/server.py`, and `frontend/src/prompts.js` (guarded by `backend/tests/test_prompt_tool_sync.py`).
- Frontend conventions (root): use `TOOL_MAP` for lookups; `ERROR_PREFIX` (⚠️) is the shared error sentinel; streaming callbacks use `setConversations` functional updaters. Backend imports use relative form inside `backend/`.
- File naming for user-facing artifacts: hyphens, never underscores, per NEH file governance.

## Working rules

- Read this file, the matching `.github/instructions/*.instructions.md` file, `AGENTS.md`, `CLAUDE.md`, task acceptance criteria, and nearby code before making changes.
- Make the smallest correct change. Avoid unrelated refactors.
- Prefer explicit, typed, tested, maintainable code.
- Preserve public APIs, request/response schemas, environment variable names, filenames, workflow names, and deployment behavior unless the task explicitly requires a change.
- Add or update tests for behavior changes.
- Update README/RUNBOOK/docs/CHANGELOG when user-facing or operational behavior changes.
- Do not fabricate files, commands, test results, credentials, policy claims, citations, billing rates, or implementation status. Billing thresholds and payer rates carry confidence labels and a `rate_source` — never upgrade a label without a verifying source.
- State validation performed. If tests cannot be run, explain exactly why.

## Source precedence

Use the highest-authority available source:

1. Current user request and acceptance criteria
2. Repository files and current code
3. Matching `.github/instructions/*.instructions.md` (path-scoped rules win for their paths)
4. `.github/copilot-instructions.md` (this file — repository-wide baseline)
5. `AGENTS.md` / root `CLAUDE.md`
6. Current issue, PR, or release plan
7. Historical docs or comments

If sources conflict, stop and call out the conflict before making a risky change.

## Security and privacy

Never commit or expose:

- PHI, patient identifiers, raw clinical excerpts, dates of service
- 42 CFR Part 2 substance use disorder records or references to them
- payer/member identifiers
- privileged legal strategy
- secrets, tokens, private keys, credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AUDIT_SALT`, Cloudflare API tokens and Access tags, Stripe, Supabase, GHCR tokens, Azure credentials, Teams webhook URLs)
- sensitive source paths or private infrastructure details
- real production data in tests or fixtures

Use synthetic examples only. Keep logs and errors free of secrets and sensitive data. The backend's audit log is hash-only by design (`backend/audit.py`) — log content hashes and metadata, never message payloads; do not weaken the salting. `corpus/` contains public federal regulation text only — never clinical excerpts, patient material, or licensed content. `/api/health` is unauthenticated and must not disclose model, corpus, embedder, auth-disabled, or default-salt state.

## GitHub Actions

For workflows (`ci.yml`, `deploy-azure.yml`, `deploy-pages.yml`, `python-publish.yml`):

- Set explicit least-privilege `permissions` at workflow or job level.
- Avoid `pull_request_target` unless explicitly required and reviewed.
- Never check out or execute untrusted PR code in a privileged context.
- Do not introduce unpinned actions; every action is pinned to a full-length commit SHA (Dependabot bumps them weekly).
- Use environment protection and required reviewers for deployment secrets (the `production` environment gates `deploy-azure.yml`; Cloudflare Pages and PyPI publish belong in protected environments too).
- Prefer OIDC over long-lived cloud credentials (PyPI trusted publishing; the Azure service principal is the current exception — do not widen its scope).

## Commits, branches, and PRs

- Branch names: `feat/`, `fix/`, `docs/`, `ci/`, `chore/` prefix plus a short kebab-case slug.
- Commit messages: imperative mood, subject 72 characters or fewer, body explains why.
- One logical change per PR. Link the issue. Label breaking or risky changes.

## Copilot code review priorities

Review in this order:

1. Security and privacy violations per this file — PHI or secrets in code, tests, fixtures, or logs; auth bypasses or fail-open changes in `backend/auth.py` (the admin audit gate fails shut); weakening of hash-only audit logging; internals leaked through `/api/health`.
2. Correctness and missing tests — billing-threshold and rule-engine logic in `scripts/`, backend request validation, retriever behavior, prompt/tool sync, frontend chat state.
3. API/schema/workflow stability — request/response models, environment variable contracts, the five-place tool-ID sync, CI and deploy workflow behavior, plugin byte-identity.
4. Maintainability and typing.
5. Style. Do not request stylistic churn that ESLint already governs; there is no Python formatter configured, so flag only genuine readability problems in Python.

## Pull request quality gate

Before proposing or finalizing a PR:

- Build passes (workbench and frontend) or limitation stated
- Tests pass (backend + root suites, frontend Vitest) or limitation stated
- Lint checks pass (frontend ESLint) or limitation stated
- Security/privacy review completed
- Docs and CHANGELOG updated when needed
- Risky or breaking changes clearly labeled
- Rollback or mitigation noted for operational changes (deploys, Docker, Fly, Cloudflare, Azure)

## Changelog

- 1.2.0 (2026-09-20): Reconciled the NEH-template set (1.1.1) with the MedSync8 set from PR #10 (1.0.0). Three-track repository context, five-place tool-ID sync, no-Python-linter rule, expanded secrets list, corpus content rule, `/api/health` disclosure rule, Cloudflare/PyPI/Azure deployment environments, merged review priorities. `frontend.instructions.md` adopted from PR #10 and extended to the root workbench.
- 1.1.1 (2026-07-23): Adapted for MedSync8 — repo context, tool-ID four-place sync, hash-only audit, billing-script anti-fabrication rules, repo-specific secrets list, workflow inventory.
- 1.1.0 (2026-07-03): Added Repository context, commit/branch/PR conventions, code review priorities, Part 2 records to exclusions, in-file versioning. Corrected source precedence so path-scoped instructions win for their paths.
- 1.0.0 (2026-08-16, `main`): Initial MedSync8 instruction set: root file plus `AGENTS.md` and path-scoped rules for workflows, Python, frontend, docs, and tests.
- 1.0.0 (2026-06-28, template): Initial release.
