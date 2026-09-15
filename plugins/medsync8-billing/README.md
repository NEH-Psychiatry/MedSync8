# medsync8-billing Plugin

CoCM/BHI billing decision support for Claude Code, packaged as one installable plugin.

## What you get

- **MCP server** (`medsync8-billing`) — six read-only tools: `billing_evaluate_cocm`, `billing_evaluate_bhi`, `billing_list_codes`, `billing_get_rate`, `billing_price_claim`, `billing_evaluate_panel`. Evaluators accept `apcm_enrolled` for the G0568/G0569/G0570 pathway; every pricing tool returns rule `warnings`.
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

- `WI_MEDICAID_RATES_JSON` — real ForwardHealth portal amounts, e.g. `{"99492": 101.50}` (overrides the labeled estimate).
- `WI_MEDICAID_FACTOR` — estimate factor when no override is loaded (default 0.70).

## Source of truth

`server/cocm_time_tracker.py` is a vendored copy of the canonical `scripts/cocm_time_tracker.py` in the MedSync8 repo — vendored so the plugin is self-contained when installed elsewhere. `tests/test_plugin_sync.py` in the repo fails CI if the copies drift. Update the canonical script first, then re-copy.

## Disclaimer

Decision-support only. Verify against the current CMS Physician Fee Schedule and the ForwardHealth portal before claim submission. Sources: CMS MLN909432 (Jan 2026) · CMS-1832-F (90 FR 49266) · MM14315 · NACHC APCM Tip Sheet (Mar 2026) · AIMS Center. Tool responses carry `warnings` for holds, discontinued codes, missing prerequisites, and same-month exclusivity — a warned claim must not be submitted.
