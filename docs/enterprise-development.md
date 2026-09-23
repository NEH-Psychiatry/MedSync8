# Enterprise Development Guide — MedSync8

How to develop, review, and ship this codebase at enterprise standard. Everything here is grounded in mechanisms that already exist in the repo — this is the operating manual for them, not aspiration.

## 1. The Trust Model in One Paragraph

MedSync8 is healthcare-adjacent software: no PHI is in the system today, but every layer is built as if PHI arrives tomorrow. That single assumption drives the rules below — hash-only audit logging, synthetic-only test data, fail-shut admin endpoints, secrets in Key Vault, and an instruction layer that binds AI coding agents to the same rules as humans. The go/no-go gate for actual PHI is contractual, not technical: Anthropic BAA + cloud BAA + local embeddings confirmed (`RUNBOOK.md`).

## 2. Development Workflow

1. **Branch** — `feat/`, `fix/`, `docs/`, `ci/`, `chore/` + kebab-case slug. One logical change per PR.
2. **Develop** — smallest correct change; read `CLAUDE.md` and the matching `.github/instructions/*.instructions.md` first. AI agents are bound by `AGENTS.md` automatically.
3. **Test locally** — `python -m pytest backend/tests tests -q` and `npm run build`. Backend tests are network-free by design (`StubEmbedder`/`StubAnthropic`); keep them that way — a new external dependency gets a stub in `conftest.py`, never a live call.
4. **Billing changes** — any edit to `scripts/cocm_time_tracker.py` triggers three gates: boundary-value tests at the CMS edges (35/36, 30/31, target+15/+16, 19/20), the `billing-auditor` agent re-audit, and the plugin sync test (`tests/test_plugin_sync.py` — re-copy the vendored file).
5. **PR** — CI runs both pytest suites and the frontend build on SHA-pinned actions. The quality gate in `.github/copilot-instructions.md` applies: build/tests/lint pass or limitation stated, security review done, risky changes labeled, rollback noted for operational changes.
6. **Merge to `main`** — triggers the Azure deploy behind the `production` environment gate (required reviewers).

## 3. Secrets — One Direction of Travel

Secrets flow one way: **GitHub encrypted secrets → deploy-time seed → Key Vault → runtime reference.** The Container App reads `keyVaultUrl` references with a user-assigned managed identity (Key Vault Secrets User — read, not manage); secret values never sit in Container Apps configuration, code, or logs.

- Never commit a secret, an "expired" test token, or a real webhook URL — fixtures use `SECRET_REDACTED_FOR_TESTS` patterns.
- Rotation: change the GitHub secret → next deploy re-seeds the vault. `AUDIT_SALT` rotation deliberately unlinks old query hashes — document the rotation date if audit continuity matters.
- Local dev uses `.env` (gitignored); the Express server exits without `ANTHROPIC_API_KEY`, which is the intended failure mode.

## 4. Data Classification Rules

| Class | Examples | Where allowed |
|---|---|---|
| Prohibited everywhere | PHI, patient identifiers, dates of service, 42 CFR Part 2 records, payer/member IDs | Nowhere — including fixtures, `corpus/`, comments, commit messages, card payloads |
| Hash-only | User queries | `backend/audit.py` salted SHA-256; never raw text, never weakened salting |
| Synthetic only | Test patients, panels, NPIs | `PT-001`-style IDs, checksummed test NPIs, declared fake date ranges |
| Labeled estimates | Payer rates | Confidence labels (`portal_verified`, `verified_primary`, `verified_secondary`, `estimated`) with a file-and-date `source` on every rate — never upgrade a label without a verifying source; an unverified slot stays unpriced rather than estimated |

## 5. Access Control Pattern

Three tiers, implemented in `backend/auth.py`:

1. **Public** — `/api/health`. Attests `access_enforced: true` when auth is on; deliberately silent when it's off (don't advertise the unlocked door).
2. **Authenticated** — `/api/chat`. Cloudflare Access JWT (`require_access`); identity flows into the audit record.
3. **Admin** — `/api/audit/recent`. `require_admin`: Access JWT **and** membership in `AUDIT_ADMIN_EMAILS`. Fails shut: auth on + allowlist unset = 403.

The pattern to reuse for any new endpoint: pick the tier explicitly, and if in doubt, fail shut. Dev mode (no CF config) opens everything — acceptable only because production is defined as "CF vars set."

## 6. AI-Agent Governance

Coding agents (Copilot, Claude Code, Codex) are first-class developers here and governed like it:

- **Instruction layer** — `.github/copilot-instructions.md` (baseline, versioned + changelog), `AGENTS.md` (operational rules), path-scoped `.github/instructions/*` (win for their paths). Instructions changes are their own task type — agents may not self-modify governance.
- **Specialized agents** — `billing-auditor` derives expected CMS results *before* reading the code, then boundary-tests. Adversarial by design: it reports, never edits.
- **Precedence ladder** — user request → repo code → path-scoped instructions → baseline → AGENTS/CLAUDE.md → issue/PR → history. Conflicts stop work; they don't get silently resolved.
- **Anti-fabrication** — validation is stated honestly ("tests could not run because X" beats a fabricated pass). Billing rates, thresholds, and citations require sources.

## 7. Supply Chain

- Actions pinned to full-length commit SHAs; Dependabot bumps SHAs weekly and dependencies monthly (grouped; npm majors held for manual review because majors can need config work — the vite 5→8 upgrade was verified by hand).
- Dependency additions need a one-line justification in the PR. `backend/requirements-test.txt` stays torch-free so CI installs fast.
- The plugin marketplace (`plugins/`) vendors the billing tracker; CI enforces byte-identity with the canonical script.

## 8. Observability & Audit

- **Audit log** — append-only JSONL on the persistent `/data` volume: salted query hash, user identity, tool, latency, citation count. Reviewable via the admin endpoint. Treat it as evidence: no retro-edits, rotation documented.
- **Logs** — Log Analytics, 90-day retention. Log lines carry no PHI, secrets, or member identifiers — structured metadata only.
- **Health** — liveness/readiness probes hit `/api/health`; scale 0→3 on HTTP concurrency.

## 9. Incident Basics

- Deploy rollback: re-run the deploy workflow at the previous image SHA (GHCR keeps every `sha-*` tag), or `az containerapp revision` to the prior revision.
- Secret compromise: rotate the GitHub secret, redeploy (re-seeds Key Vault), revoke the old value at the provider. For `AUDIT_SALT`, note the unlinking consequence.
- Suspected PHI in the repo: treat as an incident, not a cleanup — history rewrite decisions and disclosure obligations go through counsel first (see `AGENTS.md` hard boundaries and the governance layer).

## 10. Definition of Enterprise-Ready (per change)

- [ ] Tests pass (both suites) or limitation stated honestly
- [ ] No new data-classification violations (§4)
- [ ] Endpoint tier chosen explicitly for any new route (§5)
- [ ] Secrets untouched or flowing through the Key Vault path (§3)
- [ ] Billing edits: boundary tests + auditor + plugin sync (§2.4)
- [ ] Docs updated where behavior changed; changelog where governance changed
- [ ] Rollback path known before merge to `main`
