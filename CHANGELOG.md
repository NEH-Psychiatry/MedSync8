# Changelog

All notable user-facing or operational changes. Governance-file changes
carry their own in-file changelog (`.github/copilot-instructions.md`).

## Unreleased — branch `claude/update-codebase-vA58U`

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
- `/api/audit/recent` is admin-only (`AUDIT_ADMIN_EMAILS`, fails shut).
- `/api/health` attests `access_enforced: true` when Cloudflare Access is on.
- Model `claude-opus-4-8` with adaptive thinking.

### Operations
- Azure Container Apps deployment (Bicep) with Key Vault-backed secrets and
  a user-assigned managed identity; GitHub Actions deploy workflow.
- All workflow actions SHA-pinned; Dependabot enabled; npm audit at zero.
- NEH Copilot governance instruction set; `billing-auditor` agent;
  `medsync8-billing` plugin marketplace; enterprise development guide.
