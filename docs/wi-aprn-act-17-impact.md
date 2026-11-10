# 2025 Wisconsin Act 17 (APRN Modernization) — impact on the MedSync8 billing and credentialing stack

Status: analysis note, 2026-11-10. Derived from an informational summary of the Act (filed at `corpus/wisconsin/aprn-independent-practice-2025-act-17.md`); confirm against the statute text and Board of Nursing rules before acting. Decision support, not legal advice.

## What the Act changes

- From 2026-09-01 Wisconsin APNP certificates become APRN licenses automatically. Independent practice (no physician or dentist collaborative agreement) requires 3,840 documented RN-level hours over at least 24 months, then 3,840 APRN-level hours over at least 24 months with a physician or dentist immediately available, then Board authorization.
- Employers may still require collaborative agreements as a condition of employment. Invasive pain-syndrome treatment still requires a pain-medicine physician agreement.
- Renewal is biennial with 16 CE hours in pharmacology or therapeutics, 2 of them on responsible controlled-substance prescribing. Malpractice at IPFCF minimums is mandatory; independents outside an employment relationship enroll in the IPFCF.

## What the Act does not change

The Act is state scope-of-practice law. Medicare payment rules, ForwardHealth coverage and rendering-provider rules, and commercial contracts are untouched. In the billing model this is now stated on the `wi-medicaid` payer model so every rate lookup carries it: independent authority does not by itself make an NP an eligible CoCM billing practitioner, and a psychiatrist remains a consultant under ForwardHealth topic #22557.

## Where it touches this repository

| Surface | Effect | Action |
|---|---|---|
| `scripts/cocm_time_tracker.py` (`PAYER_MODELS`, `SOURCES`) | Caveat and citation added. No rate or threshold changes. | Done in this change. |
| Capacity planner (`PlanningAssumptions`) | The workbook's consultant assumptions (PMHNP hours, "licensed psychiatric NP assumed qualified for applicable payer role") remain practice assumptions, not payer facts. | Unchanged; verify payer role before relying on NP-billed CoCM revenue. |
| `scripts/credentialing_alert.py` | Classifies licenses by expiry bands only; it has no field for independent-practice authorization, supervised-hour totals, or IPFCF enrollment. | Add workbook columns for APRN authorization date, cumulative supervised hours, and IPFCF status before encoding any Act 17 rule; synthetic fixtures only. |
| Collaborative practice agreement templates (Dropbox, not in repo) | For Wisconsin APRNs who obtain independent authorization, the legal basis for a mandatory agreement ends; the agreement can continue as an employment or quality condition. | Legal review of the Wisconsin template and of each active Wisconsin agreement's termination and renewal clauses. |
| RAG corpus | Both documents are indexed under `corpus/wisconsin/` so the policy and consult tools ground answers in them. | Rebuild the index on next backend start. |

## Open questions for counsel or the Board

1. Whether supervised APRN-level hours accrued under a telepsychiatry collaboration (collaborator available remotely) satisfy "immediately available for consultation".
2. Whether the Board's forthcoming rules add specialty-specific requirements for psychiatric-mental health NPs.
3. How ForwardHealth and NGS J6 treat an independently authorized NP as the CoCM treating practitioner, which the MAC inquiry (`docs/mac-inquiry-apcm-addons.md`) does not currently ask.
