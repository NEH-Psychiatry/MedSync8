# Changelog

All notable user-facing or operational changes. Governance-file changes
carry their own in-file changelog (`.github/copilot-instructions.md`).

## Unreleased — branch `claude/update-codebase-vA58U`

### Billing model rebuilt on real numbers — plugin 2.0.0 (breaking)
- **Rates are explicit data, not factors.** Every (code, payer) amount is a
  `Rate(usd, confidence, source, note)` transcribed from the practice's
  rate-verification workbook (`NEH-CoCM-Spravato-FQHC-Consolidated-
  2026-09-20.xlsx`, Rates sheet) and the WI CoCM rate-card memo (V1.0,
  2026-09-07). The GPCI factor (0.952) and the Medicaid factor (0.70) are
  gone; a slot without a verified amount is **unpriced** (with an
  `unpriced_reason`) rather than estimated.
- **Payers renamed.** `medicare-wi` = Medicare PFS, Wisconsin locality,
  computed from CMS RVU26C (99492 $153.19 · 99493 $138.71 · 99494 $58.72;
  G2214 $58.01 · 99484 $55.04 · G0568 $154.25 · G0569 $139.45 · G0570
  $55.36 from the RVU26A memo, `verified_secondary` until re-verified).
  `medicare-fqhc` = CMS designated RHC/FQHC care-coordination rates
  (99492 $160.32 · 99493 $144.96 · 99494 $61.46). `wi-medicaid` =
  ForwardHealth fee-for-service max fees, official 2026-09-05 snapshot
  (99492 $146.05 · 99493 $141.61 · 99494 $60.51) — roughly 95% of Medicare
  WI, not the 70% the old factor assumed. **`medicare-natl` is retired**:
  the July memo's "national" figures were the FQHC designated rates.
  Requests naming it fail with a message pointing to the replacement.
- **G2214 is Medicare-only** (absent from every ForwardHealth schedule,
  verified 2026-07-30 and 2026-09-05): a WI Medicaid month under the base
  minimum is non-billable and reported as unbilled care-manager time.
  99484 has no WI Medicaid amount in the verification set (prior finding
  ~75% of Medicare) and stays unpriced until loaded.
- New confidence label `verified_primary` (read or computed from the
  payer's published primary file; file and date in `source`), ranked
  between `portal_verified` and `verified_secondary`.
- `RATE_OVERRIDES_JSON` (per payer, each entry with its own confidence and
  source; bare numbers accepted) replaces `WI_MEDICAID_FACTOR`; the legacy
  `WI_MEDICAID_RATES_JSON` shorthand still works.
- `PAYER_MODELS` carries each payer's description, source and caveat (a
  psychiatrist cannot be the WI CoCM billing practitioner; CHCs use the
  T1015 PPS pathway) — surfaced by `--list-codes` and `billing_get_rate`.
- **Capacity planning.** `plan_capacity()` / `blended_month_allowance()`,
  CLI `--capacity-plan N --payer-mix …`, and the seventh MCP tool
  `billing_plan_capacity` convert an active panel into billable months,
  expected 99492/99493/99494 units, BHCM FTE (exact and budget-rounded)
  and allowance per payer. Defaults are the workbook's planning inputs
  (80% billable conversion, 15% initial-month share, 0.2 extra units, 60
  patients/FTE, 94% realization, private at 125% of Medicare WI —
  estimated) and reproduce its CoCM rows exactly ($159.56 / $152.63 /
  $154.38 per billable month; 125 active → 100 billable months, 2.1 FTE).
- CLI default payer is now `medicare-wi`; `mcp/evaluation.xml` re-derived
  (12 questions). `billing_list_codes` returns `rates` keyed by payer.

### Merged `main` (PR #10, 2026-09-15) — 19 conflicts reconciled
- Governance: the two independently authored instruction sets are merged
  into `.github/copilot-instructions.md` v1.2.0, `AGENTS.md`, and the
  path-scoped files; where they differed the stricter rule was kept.
  `frontend.instructions.md` (from `main`) now also covers the root
  workbench.
- Backend: PR #10's JWKS force-refetch on unknown `kid` (rate-limited) is
  combined with this branch's lock; PR #10's request-shape validation,
  message limits, salt helper, and indexing-failure degradation are kept;
  this branch's fail-shut admin audit gate, minimal `/api/health` (no
  internals, never advertises auth-disabled or default-salt state), and
  explicit upstream timeouts win. Every test from both sides survives (the
  lifespan regression test now asserts on app state rather than a health
  field the endpoint deliberately does not expose).
- Frontend: PR #10's `frontend/` files are taken as-is; `prompts.js` gains
  the `documentation` tool so the prompt/tool sync contract holds.
- CI: frontend lint is mandatory (no `--if-present`); README, root
  `.env.example`, and the devcontainer describe all three tracks.
- Added `docs/mac-inquiry-apcm-addons.md` — the written MAC inquiry for
  G0568–G0570 with the answer-to-code-change map.

### Billing model — plugin 1.1.0
- **APCM-enrolled pathway.** `--apcm-enrolled yes` (CLI), `apcm_enrolled`
  (MCP inputs and panel patients) evaluates a patient receiving APCM
  (G0556–G0558) from the same practitioner: the eligible code becomes the
  G0568/G0569/G0570 add-on with `cpt_alternative` carrying the CPT set;
  below the CPT midpoint minimum the G-code is not recommended — a
  **practice policy stricter than CMS-1832-F**, which sets no minute
  requirement for the add-ons; revisit when written MAC confirmation
  arrives. Pricing still returns the hold and APCM-base warnings.
- APCM base codes G0556/G0557/G0558 are catalogued (no rate) so a
  correctly formed APCM claim no longer raises "unknown code".
- Open item for the MAC letter: whether G2214 may be reported in an APCM
  month alongside or instead of G0568/G0569 is not encoded (no source).
- Tests added for `scripts/credentialing_alert.py` (bands, date coercion,
  workbook loading with real openpyxl tables, Teams delivery with a mocked
  transport, exit codes) and for the MCP tool layer (contracts, warnings,
  validation, `evaluation.xml` through the tools). `openpyxl` and `mcp`
  added to `backend/requirements-test.txt`.

### Billing model (`scripts/cocm_time_tracker.py`, MCP tools, plugin)
- **Rules are now enforced, not just described.** `BillingCode` carries
  `status` (active/hold/discontinued), `mirror_of`, `requires_any_of`,
  `exclusive_with`, `payers`, and `rate_source`; `price_claim()` returns
  `warnings` for same-month exclusivity (G-code + mirror CPT, G2214 vs base,
  99484 vs base), missing prerequisites (99494 without a base, APCM add-on
  without G0556–G0558), billing holds, and discontinued codes. All MCP tools
  surface these warnings.
- **CY2026 rates corrected** to the July 2026 verified figures: 99492
  $160.32, 99493 $144.96, 99494 $61.46, G2214 $60.79. 99484 $57.78 is
  crosswalk-derived and labeled `estimated`.
- **APCM add-ons G0568/G0569/G0570** priced ($161.66 / $145.96 / $57.78,
  NACHC CMS-derived), status `hold` pending written MAC confirmation,
  Medicare-only (no WI Medicaid estimate is generated for them).
- **G0512 discontinued** effective 2026-01-01; returns a distinct
  `discontinued` status rather than "not modeled". The
  `rhc_fqhc_alternative` result key was removed.
- Every rate has a `rate_source`; a single `SOURCES` list feeds the CLI
  epilog, `--list-codes`, per-run output, and the MCP disclaimer.
- CLI output keys changed: `estimated_payment_usd`, `rate_confidence`,
  `rate_source`, `warnings`, `threshold_confidence`, `sources`.
- MCP servers support the MCP Python SDK 1.x and 2.x (`mcp>=1.2,<3`).

### Frontend
- **Restored `frontend/`**, the RAG client for the FastAPI backend (citations
  UI, vitest suite, Cloudflare Pages deploy). It had been removed as a
  "duplicate" of the root Express workbench, which left the production
  backend without a client. The repo is a dual-app layout again: root
  `src/` + `server.js` (Express workbench) and `frontend/` + `backend/`
  (RAG telepsychiatry assistant). CI lints/tests/builds both.
- Root workbench: vite 8, `claude-opus-4-8` with adaptive thinking.

### Backend
- All outbound relays are time-bounded: the Anthropic client
  (`ANTHROPIC_TIMEOUT_SECONDS`, default 180) and the optional OpenAI
  embedding client (`OPENAI_TIMEOUT_SECONDS`, default 30) now carry explicit
  timeouts and retry caps, joining the Cloudflare JWKS fetch (5 s) and the
  Teams webhook (15 s). A hung upstream can no longer pin a request worker.
- `/api/audit/recent` is admin-only (`AUDIT_ADMIN_EMAILS`, fails shut).
- `/api/health` attests `access_enforced: true` when Cloudflare Access is on.
- Model `claude-opus-4-8` with adaptive thinking.

### Operations
- Azure Container Apps deployment (Bicep) with Key Vault-backed secrets and
  a user-assigned managed identity; GitHub Actions deploy workflow.
- All workflow actions SHA-pinned; Dependabot enabled; npm audit at zero.
- NEH Copilot governance instruction set; `billing-auditor` agent;
  `medsync8-billing` plugin marketplace; enterprise development guide.
