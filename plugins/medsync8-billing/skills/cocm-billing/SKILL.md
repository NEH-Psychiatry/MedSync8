---
name: cocm-billing
description: >
  CoCM/BHI billing decision support. Use when the user asks about
  Collaborative Care Model or Behavioral Health Integration billing —
  codes 99492, 99493, 99494, G2214, 99484, G0568-G0570 (APCM add-ons), the
  discontinued G0512, minute thresholds, the midpoint rule, initiating
  visits, add-on units, payer rates (Medicare national, Medicare Wisconsin,
  WI Medicaid/ForwardHealth), claim pricing, or panel revenue. Routes
  questions to the medsync8-billing MCP tools instead of answering from
  memory.
---

# CoCM/BHI Billing Decision Support

Never answer CoCM/BHI eligibility or rate questions from memory — the
medsync8-billing MCP server is the source of truth. Its thresholds implement
CMS MLN909432 and CMS-1832-F; its rules are enforced by the tools and
returned as `warnings`.

## Tool routing

| Question shape | Tool |
|---|---|
| "Can we bill X for N minutes?" (CoCM) | `billing_evaluate_cocm` (minutes, month=initial\|subsequent, initiating_visit) |
| General BHI / 99484 track | `billing_evaluate_bhi` |
| "What codes exist / what's the threshold / what's the status of…" | `billing_list_codes` (category filter) |
| "What does code X pay under payer Y?" | `billing_get_rate` |
| "Price this claim" (code list, repeats = units) | `billing_price_claim` |
| Multiple patients / monthly revenue | `billing_evaluate_panel` (synthetic IDs only — never PHI) |

## What the tools enforce (relay their output; do not restate from memory)

- **Midpoint rule**: 99492 ≥36 min (initial, target 70); 99493 ≥31
  (subsequent, target 60); 99494 add-on first unit at target+16, then every
  30, no cap; G2214 ≥30 when the base minimum is unmet; 99484 ≥20 (BHI).
- **Initiating visit** required before the first CoCM/BHI month.
- **Same-month exclusivity** (returned as warnings): 99484 vs 99492/99493;
  G2214 vs 99492/99493; 99494 requires a base code.
- **APCM add-ons G0568/G0569/G0570**: status `hold`. They require an APCM
  base code (G0556–G0558), are Medicare-only, and are *either/or* with their
  mirror CPT code (99492/99493/99484) — never both for the same
  patient-month. The supplement-vs-replace question is unresolved in the
  CY2026 rule (NACHC: "CMS Clarification Pending"); G-code billing is on hold
  pending written MAC confirmation. Any claim that the G-codes "replaced" the
  CPT codes, or that both may be stacked, is unsupported — say so and cite
  the hold.
- **G0512** is discontinued (2026-01-01). RHC/FQHC settings bill the same
  time-based codes; there is no RHC/FQHC alternative code to surface.
- **Payers**: medicare-natl, medicare-wi (GPCI estimate), wi-medicaid
  (ForwardHealth portal values where loaded, else a labeled estimate;
  Medicare-only codes return "not covered").

## Response requirements

- Always relay `rate_confidence` **and** `rate_source`; treat `estimated`
  as unverified and say so.
- Relay every entry in `warnings` verbatim before any dollar figure — a
  warned claim may be totaled for visibility but must not be presented as
  submittable.
- Relay `status` when it is `hold` or `discontinued`.
- Flag near-threshold months (within ~5 minutes of a boundary) with the
  exact minutes needed to change the result.
- Always pass through the tool's `disclaimer`.
