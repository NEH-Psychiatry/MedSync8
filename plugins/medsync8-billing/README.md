# medsync8-billing Plugin

CoCM/BHI billing decision support for Claude Code, packaged as one installable plugin.

## What you get

- **MCP server** (`medsync8-billing`) — seven read-only tools: `billing_evaluate_cocm`, `billing_evaluate_bhi`, `billing_list_codes`, `billing_get_rate`, `billing_price_claim`, `billing_evaluate_panel`, `billing_plan_capacity`. Evaluators accept `apcm_enrolled` for the G0568/G0569/G0570 pathway; every pricing tool returns rule `warnings`; every rate carries a confidence label and the CMS/ForwardHealth file it came from.
- **`/billing-check` command** — one-line eligibility and pricing checks.
- **`billing-auditor` agent** — adversarial boundary-value audit of billing logic against CMS MLN909432.
- **`cocm-billing` skill** — routes billing questions to the tools instead of model memory.

## Install

```bash
# From the MedSync8 repo as a marketplace:
/plugin marketplace add NEH-Psychiatry/MedSync8
/plugin install medsync8-billing@medsync8
```

Requires `python3` with the `mcp` package (`pip install mcp`).

## Configuration

Payer models: `medicare-wi` (Medicare PFS, Wisconsin locality, CMS CY2026 RVU26C), `medicare-fqhc` (CMS designated RHC/FQHC care-coordination rates), `wi-medicaid` (ForwardHealth fee-for-service max fees, 2026-09-05 snapshot). Slots without a verified amount are unpriced, never estimated.

- `RATE_OVERRIDES_JSON` — add or replace a rate per payer with its own provenance, e.g. `{"wi-medicaid": {"99484": {"usd": 41.28, "confidence": "verified_primary", "source": "ForwardHealth query 2026-09-21"}}}`; a bare number is accepted and labeled `portal_verified`.
- `WI_MEDICAID_RATES_JSON` — legacy shorthand for the `wi-medicaid` block, e.g. `{"99484": 41.28}`.

## Source of truth

`server/cocm_time_tracker.py` is a vendored copy of the canonical `scripts/cocm_time_tracker.py` in the MedSync8 repo — vendored so the plugin is self-contained when installed elsewhere. `tests/test_plugin_sync.py` in the repo fails CI if the copies drift. Update the canonical script first, then re-copy.

## Disclaimer

Decision-support only. Verify against the current CMS Physician Fee Schedule and the ForwardHealth portal before claim submission. Sources: CMS MLN909432 (Jan 2026) · CMS-1832-F (90 FR 49266) · MM14315 · CMS CY2026 PFS RVU26C · CMS RHC/FQHC CY2026 rates · ForwardHealth max-fee snapshot 2026-09-05 · ForwardHealth Update 2026-07 · NEH rate-verification workbook (2026-09-20) and memo (2026-09-07) · NACHC APCM Tip Sheet (Mar 2026) · AIMS Center. Tool responses carry `warnings` for holds, discontinued codes, missing prerequisites, and same-month exclusivity — a warned claim must not be submitted.
