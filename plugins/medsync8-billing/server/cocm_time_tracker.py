#!/usr/bin/env python3
"""cocm_time_tracker.py — CoCM / BHI midpoint-rule billing-eligibility helper.

Supported code families
-----------------------
CoCM (Collaborative Care Model):
  99492  Initial calendar month  (≥36 min, target 70)
  99493  Subsequent months       (≥31 min, target 60)
  99494  Add-on per 30-min block (≥16 min each, unlimited units)
  G2214  Shorter service         (≥30 min, base code minimum unmet)

General BHI (non-CoCM Behavioral Health Integration):
  99484  Per calendar month      (≥20 min)
  NOTE: 99484 cannot be billed in the same month as 99492 / 99493.

RHC / FQHC setting:
  G0512  DISCONTINUED 2026-01-01 — RHCs/FQHCs now report 99492/99493/99494/
         G2214 individually and may apply the midpoint rule (50%+1).

APCM companion add-ons (CY2026, patient must ALSO be enrolled in Advanced
Primary Care Management G0556–G0558 with the same practitioner/month):
  G0568  CoCM initial month add-on    (crosswalks 99492, wRVU 1.88)
  G0569  CoCM subsequent month add-on (crosswalks 99493, wRVU 2.05)
  G0570  General BHI add-on           (crosswalks 99484, wRVU 0.93)
  NOTE: Finalized in CMS-1832-F (90 FR 49266 §II.G) as additions to the code
  set; the standalone codes remain active. But for the SAME patient-month,
  the operating rule is EITHER the G-code OR its mirror CPT code — never
  both (same work; duplicate-service audit risk). The supplement-vs-replace
  question is unresolved in the CY2026 rule (NACHC: "CMS Clarification
  Pending"); G-code billing is ON HOLD pending written MAC confirmation.
  Not time-based — distinguished by model and episode month only.

Valid initiating visits (required before any CoCM/BHI month):
  99202-99215  Office / outpatient E/M
  G0402        Welcome to Medicare preventive visit
  G0438        Annual Wellness Visit — initial
  G0439        Annual Wellness Visit — subsequent
  99495        Transitional Care Management — 14-day + moderate complexity
  99496        Transitional Care Management — 7-day + high complexity
  90791        Psychiatric diagnostic evaluation
  90792        Psychiatric diagnostic evaluation with medical services

Payer rate model (--payer)
--------------------------
  medicare-natl  CY2026 national non-facility PFS (verified where possible)
  medicare-wi    Wisconsin statewide locality estimate = national × 0.952
                 (GPCIs: work 1.000 floor, PE ~0.94 est., MP 0.331; PE-heavy mix)
  wi-medicaid    Wisconsin Medicaid (ForwardHealth / BadgerCare Plus).
                 Exact amounts live in the ForwardHealth interactive Max Fee
                 Schedule (physician services) — portal lookup only; the
                 public per-program PDFs (e.g. the Community Support Program
                 schedule) do NOT carry these codes and must not be used.
                 Two options:
                   1. Set WI_MEDICAID_RATES_JSON='{"99492": 101.50, ...}'
                      with real portal values (preferred).
                   2. Otherwise an ESTIMATE of national × WI_MEDICAID_FACTOR
                      (default 0.70) is used and labeled estimated_unverified.

Decision-support only; verify against the current CMS Physician Fee Schedule
and the ForwardHealth portal. Source: CMS MLN909432 · CMS-1832-F · AIMS Center
CoCM Implementation Guide · CPT 2026.

Usage examples
--------------
    # CoCM — initial month, 72 min accrued, priced at WI Medicare estimate
    python3 cocm_time_tracker.py --minutes 72 --month initial \
        --initiating-visit yes --payer medicare-wi

    # CoCM — subsequent month with an add-on unit
    python3 cocm_time_tracker.py --minutes 116 --month subsequent --initiating-visit yes

    # General BHI (no CoCM registry required), WI Medicaid estimate
    python3 cocm_time_tracker.py --mode bhi --minutes 25 --initiating-visit yes \
        --payer wi-medicaid

    # Print the full code catalogue with the rate table and exit
    python3 cocm_time_tracker.py --list-codes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Code catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BillingCode:
    code: str
    description: str
    category: str
    target_min: int | None       # typical service-time target
    min_to_bill: int | None      # midpoint-rule minimum required to bill
    medicare_natl: float | None = None  # CY2026 national non-facility, USD
    wi_medicaid: float | None = None    # ForwardHealth portal max fee, USD
    rate_confidence: str = ""    # verified_secondary | estimated | (blank = n/a)
    notes: str = ""


COCM_CODES: list[BillingCode] = [
    BillingCode(
        "99492", "CoCM — initial calendar month", "CoCM",
        target_min=70, min_to_bill=36,
        medicare_natl=160.32, rate_confidence="verified_secondary",
        notes="First month of CoCM enrollment only. Requires patient registry, "
              "care plan, and systematic caseload review by the supervising provider.",
    ),
    BillingCode(
        "99493", "CoCM — subsequent calendar month", "CoCM",
        target_min=60, min_to_bill=31,
        medicare_natl=144.96, rate_confidence="verified_secondary",
        notes="Every month after the initial month.",
    ),
    BillingCode(
        "99494", "CoCM — each additional 30-min block (add-on ×N)", "CoCM",
        target_min=30, min_to_bill=16,
        medicare_natl=61.46, rate_confidence="verified_secondary",
        notes="Add-on to 99492 or 99493. One unit per 30-min increment past the "
              "base target. No cap on number of units per month.",
    ),
    BillingCode(
        "G2214", "CoCM / BHI — shorter first- or subsequent-month service", "CoCM",
        target_min=30, min_to_bill=30,
        medicare_natl=60.79, rate_confidence="verified_secondary",
        notes="For patients with ≥30 min who don't meet the base code minimum. "
              "Cannot combine with 99492 / 99493 in the same month.",
    ),
]

BHI_CODES: list[BillingCode] = [
    BillingCode(
        "99484", "General BHI — per calendar month", "General BHI",
        target_min=20, min_to_bill=20,
        medicare_natl=57.78, rate_confidence="verified_secondary",
        notes="Non-CoCM path. BHI clinical staff ≥20 min/month. No registry or "
              "systematic caseload review required. Cannot bill 99484 and "
              "99492 / 99493 in the same month.",
    ),
]

FQHC_CODES: list[BillingCode] = [
    BillingCode(
        "G0512", "RHC/FQHC psychiatric CoCM — DISCONTINUED 2026-01-01", "RHC/FQHC",
        target_min=None, min_to_bill=None,
        notes="Discontinued effective 2026-01-01 (CY2026 final rule). RHCs and "
              "FQHCs now report 99492/99493/99494/G2214 individually and may "
              "apply the midpoint rule (50%+1) to those time-based codes. "
              "Retained here for historical claims only.",
    ),
]

APCM_ADDON_CODES: list[BillingCode] = [
    BillingCode(
        "G0568", "APCM add-on — CoCM initial month (crosswalks 99492, wRVU 1.88)",
        "APCM add-on",
        target_min=None, min_to_bill=None,
        medicare_natl=161.66, rate_confidence="verified_secondary",
        notes="CY2026. Billable only when an APCM base code (G0556–G0558) is "
              "reported by the same practitioner in the same month. NOT "
              "time-based. Either/or rule: never report both the G-code and "
              "its mirror CPT code for the same patient-month — same work, "
              "duplicate-service audit risk. BILLING HOLD pending written MAC "
              "confirmation (supplement-vs-replace unresolved in CY2026 rule).",
    ),
    BillingCode(
        "G0569", "APCM add-on — CoCM subsequent month (crosswalks 99493, wRVU 2.05)",
        "APCM add-on",
        target_min=None, min_to_bill=None,
        medicare_natl=145.96, rate_confidence="verified_secondary",
        notes="CY2026. Same APCM-base requirement, either/or rule, and MAC-"
              "confirmation hold as G0568. Distinguished from G0568 by episode "
              "month (initial vs subsequent), not time or complexity.",
    ),
    BillingCode(
        "G0570", "APCM add-on — General BHI (crosswalks 99484, wRVU 0.93)",
        "APCM add-on",
        target_min=None, min_to_bill=None,
        medicare_natl=57.78, rate_confidence="verified_secondary",
        notes="CY2026. General BHI model — no psychiatric consultant. Same "
              "APCM-base requirement, either/or rule, and MAC-confirmation "
              "hold as G0568.",
    ),
]

# ForwardHealth BHIC contract rows (portal extract, effective 2014-04-01,
# no end date; provider types 11/801-803; rate type MAXFEE). This is WI
# Medicaid's integrated-care billing pathway — distinct from the CPT CoCM
# family, whose ForwardHealth coverage/rates still require a portal check.
WI_MEDICAID_BHIC_CODES: list[BillingCode] = [
    BillingCode(
        "H0038", "Self-help / peer services, per 15 min", "WI Medicaid BHIC",
        target_min=15, min_to_bill=15,
        wi_medicaid=5.75, rate_confidence="portal_verified",
        notes="ForwardHealth BHIC contract. Billed in 15-min units.",
    ),
    BillingCode(
        "S0280", "Medical home — comprehensive care coordination and planning, "
                 "initial plan", "WI Medicaid BHIC",
        target_min=None, min_to_bill=None,
        wi_medicaid=473.64, rate_confidence="portal_verified",
        notes="ForwardHealth BHIC contract. One-time initial care plan.",
    ),
    BillingCode(
        "S0281", "Medical home — care coordination, maintenance of plan",
        "WI Medicaid BHIC",
        target_min=None, min_to_bill=None,
        wi_medicaid=13.14, rate_confidence="portal_verified",
        notes="ForwardHealth BHIC contract. Ongoing plan maintenance.",
    ),
]

INITIATING_VISIT_CODES: list[BillingCode] = [
    BillingCode(
        "99202-99215", "Office / outpatient E/M visit", "Initiating",
        target_min=None, min_to_bill=None,
        notes="Most common. Must address the behavioral health condition.",
    ),
    BillingCode(
        "G0402", "Welcome to Medicare preventive visit", "Initiating",
        target_min=None, min_to_bill=None,
    ),
    BillingCode(
        "G0438", "Annual Wellness Visit — initial", "Initiating",
        target_min=None, min_to_bill=None,
    ),
    BillingCode(
        "G0439", "Annual Wellness Visit — subsequent", "Initiating",
        target_min=None, min_to_bill=None,
    ),
    BillingCode(
        "99495", "Transitional Care Management — 14-day contact, moderate complexity",
        "Initiating", target_min=None, min_to_bill=None,
    ),
    BillingCode(
        "99496", "Transitional Care Management — 7-day contact, high complexity",
        "Initiating", target_min=None, min_to_bill=None,
    ),
    BillingCode(
        "90791", "Psychiatric diagnostic evaluation", "Initiating",
        target_min=None, min_to_bill=None,
        notes="Common initiating visit at NEH. No medical services component.",
    ),
    BillingCode(
        "90792", "Psychiatric diagnostic evaluation with medical services", "Initiating",
        target_min=None, min_to_bill=None,
        notes="Includes medication management; typical for prescribing providers at NEH.",
    ),
]

ALL_CODES = (
    COCM_CODES + BHI_CODES + FQHC_CODES + APCM_ADDON_CODES
    + WI_MEDICAID_BHIC_CODES + INITIATING_VISIT_CODES
)
CODE_MAP: dict[str, BillingCode] = {c.code: c for c in ALL_CODES}


# ---------------------------------------------------------------------------
# Payer rate model
# ---------------------------------------------------------------------------

# Wisconsin statewide PFS locality (MAC: NGS Jurisdiction 6, contract 06302).
# GPCI mix for PE-heavy care-management codes: work 1.000 (floor, verified),
# PE ~0.94 (estimated), MP 0.331 (verified) -> blended ~0.952.
WI_GPCI_FACTOR = 0.952

# WI Medicaid (ForwardHealth) exact amounts require the interactive Max Fee
# portal (physician services schedule — NOT the per-program public PDFs such
# as the Community Support Program schedule, which don't carry these codes).
# Preferred: export real portal values, e.g.
#   WI_MEDICAID_RATES_JSON='{"99492": 101.50, "99493": 82.00}'
# Fallback: estimate as medicare_natl x WI_MEDICAID_FACTOR (default 0.70).
WI_MEDICAID_FACTOR = float(os.environ.get("WI_MEDICAID_FACTOR", "0.70"))
try:
    _WI_MEDICAID_OVERRIDES: dict[str, float] = {
        k: float(v)
        for k, v in json.loads(os.environ.get("WI_MEDICAID_RATES_JSON", "{}")).items()
    }
except (json.JSONDecodeError, TypeError, ValueError):
    print("warning: WI_MEDICAID_RATES_JSON is not valid JSON — ignoring", file=sys.stderr)
    _WI_MEDICAID_OVERRIDES = {}

PAYERS = ("medicare-natl", "medicare-wi", "wi-medicaid")


def get_rate(code: str, payer: str) -> tuple[float | None, str]:
    """Return (rate_usd, confidence_label) for a code under a payer model."""
    bc = CODE_MAP.get(code)
    if payer == "wi-medicaid":
        if code in _WI_MEDICAID_OVERRIDES:
            return _WI_MEDICAID_OVERRIDES[code], "portal_verified"
        if bc is not None and bc.wi_medicaid is not None:
            return bc.wi_medicaid, "portal_verified"
    if bc is None or bc.medicare_natl is None:
        return None, ""
    if payer == "medicare-natl":
        return bc.medicare_natl, bc.rate_confidence
    if payer == "medicare-wi":
        return round(bc.medicare_natl * WI_GPCI_FACTOR, 2), "estimated (GPCI-adjusted)"
    if payer == "wi-medicaid":
        return (
            round(bc.medicare_natl * WI_MEDICAID_FACTOR, 2),
            f"estimated_unverified ({WI_MEDICAID_FACTOR:.0%} of natl — set "
            "WI_MEDICAID_RATES_JSON with ForwardHealth portal values)",
        )
    raise ValueError(f"unknown payer: {payer}")


def price_codes(codes: list[str], payer: str) -> tuple[float | None, list[str]]:
    """Sum rates for a billed code list; returns (total, unpriced_codes)."""
    total = 0.0
    unpriced: list[str] = []
    priced_any = False
    for c in codes:
        rate, _ = get_rate(c, payer)
        if rate is None:
            unpriced.append(c)
        else:
            total += rate
            priced_any = True
    return (round(total, 2) if priced_any else None), unpriced


# ---------------------------------------------------------------------------
# Eligibility logic
# ---------------------------------------------------------------------------

def evaluate_cocm(minutes: int, month: str, initiating_visit: bool) -> dict[str, Any]:
    """Return the highest supported CoCM code set for the given month's minutes."""
    month = month.strip().lower()
    if month not in ("initial", "subsequent"):
        raise ValueError("--month must be 'initial' or 'subsequent'")

    if not initiating_visit:
        return {
            "mode": "CoCM",
            "eligible_code": None,
            "note": (
                "No initiating visit on file. CoCM enrollment requires one of: "
                "office E/M (99202–99215), Annual Wellness Visit (G0438/G0439), "
                "Welcome to Medicare (G0402), TCM (99495/99496), or psychiatric "
                "evaluation (90791/90792)."
            ),
        }

    base_code, target, base_min = (
        ("99492", 70, 36) if month == "initial" else ("99493", 60, 31)
    )
    apcm_alt = "G0568" if month == "initial" else "G0569"
    result: dict[str, Any] = {"mode": "CoCM", "accrued_minutes": minutes, "month": month}

    if minutes < base_min:
        if minutes >= 30:
            result.update(
                eligible_code="G2214",
                note=(
                    f"Base {base_code} minimum ({base_min} min) unmet. "
                    f"{minutes} min qualifies for G2214 (≥30-min shorter service)."
                ),
            )
        else:
            result.update(
                eligible_code=None,
                note=(
                    f"{minutes} min supports no CoCM code this month "
                    f"(need ≥{base_min} min for {base_code}, ≥30 min for G2214)."
                ),
            )
        return result

    # Base code met — tally add-on 99494 units.
    extra = minutes - target
    addon_units = 0
    if extra >= 16:
        addon_units = 1 + max(0, (extra - 16) // 30)

    codes = [base_code] + ["99494"] * addon_units
    next_threshold = target + 16 + addon_units * 30

    result.update(
        eligible_code=" + ".join(codes),
        base_min_met=True,
        addon_30min_units=addon_units,
        next_99494_at_min=(next_threshold if minutes < next_threshold else None),
        apcm_alternative=(
            f"{apcm_alt} — APCM-enrolled patients (G0556–G0558) ONLY; either/or "
            f"with {base_code}, never both in the same month; billing hold "
            "pending written MAC confirmation"
        ),
        note=(
            "Midpoint rule satisfied for base code. RHC/FQHC settings bill "
            "these same codes (G0512 discontinued 2026-01-01)."
        ),
    )
    return result


def evaluate_bhi(minutes: int, initiating_visit: bool) -> dict[str, Any]:
    """Return eligibility for General BHI (99484)."""
    result: dict[str, Any] = {"mode": "General BHI (non-CoCM)", "accrued_minutes": minutes}

    if not initiating_visit:
        return {
            **result,
            "eligible_code": None,
            "note": (
                "No initiating visit on file. General BHI requires an E/M or "
                "preventive visit. See --list-codes for valid initiating visit codes."
            ),
        }

    if minutes >= 20:
        result.update(
            eligible_code="99484",
            apcm_alternative=(
                "G0570 — APCM-enrolled patients (G0556–G0558) ONLY; either/or "
                "with 99484, never both in the same month; billing hold "
                "pending written MAC confirmation"
            ),
            note=(
                f"{minutes} min meets the ≥20-min minimum for 99484 (General BHI). "
                "Cannot bill 99484 in the same month as 99492 or 99493."
            ),
        )
    else:
        result.update(
            eligible_code=None,
            note=f"{minutes} min does not meet the ≥20-min minimum for 99484.",
        )
    return result


# ---------------------------------------------------------------------------
# Code catalogue display
# ---------------------------------------------------------------------------

_CATEGORY_ORDER = [
    "CoCM", "General BHI", "RHC/FQHC", "APCM add-on",
    "WI Medicaid BHIC", "Initiating",
]
_CATEGORY_LABELS = {
    "CoCM":        "CoCM — Collaborative Care Model",
    "General BHI": "General BHI — Non-CoCM Behavioral Health Integration",
    "RHC/FQHC":    "RHC / FQHC Setting",
    "APCM add-on": "APCM Companion Add-ons (CY2026 — require APCM base G0556–G0558)",
    "WI Medicaid BHIC": "WI Medicaid BHIC Contract (ForwardHealth portal — verified)",
    "Initiating":  "Valid Initiating Visit Codes (required before first CoCM/BHI month)",
}


def print_code_catalogue() -> None:
    by_cat: dict[str, list[BillingCode]] = {c: [] for c in _CATEGORY_ORDER}
    for code in ALL_CODES:
        by_cat[code.category].append(code)

    for cat in _CATEGORY_ORDER:
        codes = by_cat[cat]
        label = _CATEGORY_LABELS[cat]
        print(f"\n{'─' * 72}")
        print(f"  {label}")
        print(f"{'─' * 72}")
        for c in codes:
            time_info = ""
            if c.min_to_bill is not None and c.target_min is not None:
                time_info = f"  [≥{c.min_to_bill}–{c.target_min} min]"
            elif c.min_to_bill is not None:
                time_info = f"  [≥{c.min_to_bill} min]"
            print(f"  {c.code:<14}  {c.description}{time_info}")
            if c.notes:
                # Wrap note at 60 chars, indented
                words = c.notes.split()
                line, col = [], 0
                for w in words:
                    if col + len(w) + 1 > 60 and line:
                        print(f"  {'':14}  ↳ {' '.join(line)}")
                        line, col = [w], len(w)
                    else:
                        line.append(w)
                        col += len(w) + 1
                if line:
                    print(f"  {'':14}  ↳ {' '.join(line)}")


def print_rate_table() -> None:
    print(f"\n{'─' * 72}")
    print("  Rate table (USD per unit — decision-support estimates)")
    print(f"{'─' * 72}")
    print(f"  {'Code':<8}{'Medicare natl':>14}{'Medicare WI*':>14}{'WI Medicaid**':>15}")
    for c in COCM_CODES + BHI_CODES + APCM_ADDON_CODES + WI_MEDICAID_BHIC_CODES:
        natl, _ = get_rate(c.code, "medicare-natl")
        wi, _ = get_rate(c.code, "medicare-wi")
        mcd, mcd_conf = get_rate(c.code, "wi-medicaid")
        natl_str = f"{natl:,.2f}" if natl is not None else "—"
        wi_str = f"{wi:,.2f}" if wi is not None else "—"
        mcd_str = (
            f"{mcd:,.2f}" + ("" if mcd_conf == "portal_verified" else "~")
            if mcd is not None else "—"
        )
        print(f"  {c.code:<8}{natl_str:>14}{wi_str:>14}{mcd_str:>15}")
    print(
        "\n  *  WI = national × 0.952 (GPCI est.: work 1.000, PE ~0.94, MP 0.331).\n"
        "     Statewide locality; MAC = NGS Jurisdiction 6 (contract 06302).\n"
        f"  ** ~ = estimated at {WI_MEDICAID_FACTOR:.0%} of national — UNVERIFIED. Real\n"
        "     amounts: ForwardHealth interactive Max Fee Schedule (physician\n"
        "     services — not the per-program PDFs); supply them via\n"
        "     WI_MEDICAID_RATES_JSON to replace the estimate.\n"
        "     G0568/G0569/G0570: APCM-base required; either/or with mirror CPT\n"
        "     code; BILLING HOLD pending written MAC confirmation.\n"
        "     G0512 discontinued 2026-01-01. Sequestration not applied."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="CoCM / BHI midpoint-rule billing eligibility (decision-support only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Source: CMS MLN909432 (Jan 2026) · CMS-1832-F (90 FR 49266) · MM14315 · NACHC APCM Tip Sheet (Mar 2026) · AIMS Center\n"
            "Disclaimer: Decision-support only. Verify against the current CMS fee\n"
            "schedule and the ForwardHealth portal before claim submission."
        ),
    )
    ap.add_argument(
        "--mode", choices=["cocm", "bhi"], default="cocm",
        help="cocm (default): Collaborative Care Model  |  bhi: General BHI (99484)",
    )
    ap.add_argument("--minutes", type=int,
                    help="Accrued BH care-manager clinical minutes this calendar month")
    ap.add_argument("--month", help="cocm mode only: initial | subsequent")
    ap.add_argument("--initiating-visit", help="yes | no")
    ap.add_argument(
        "--payer", choices=PAYERS, default="medicare-natl",
        help="Rate model for estimated payment (default: medicare-natl)",
    )
    ap.add_argument("--list-codes", action="store_true",
                    help="Print the full supported code catalogue + rate table and exit")
    args = ap.parse_args()

    if args.list_codes:
        print_code_catalogue()
        print_rate_table()
        print(
            "\nSource: CMS MLN909432 (Jan 2026) · CMS-1832-F (90 FR 49266) · MM14315 · NACHC APCM Tip Sheet (Mar 2026) · AIMS Center"
        )
        print("Disclaimer: Decision-support only. Verify against current CMS fee schedule.")
        return 0

    if args.minutes is None:
        ap.error("--minutes is required")
    if args.initiating_visit is None:
        ap.error("--initiating-visit is required")

    iv = args.initiating_visit.strip().lower() in ("yes", "y", "true", "1")

    if args.mode == "bhi":
        result = evaluate_bhi(args.minutes, iv)
    else:
        if not args.month:
            ap.error("--month (initial | subsequent) is required in cocm mode")
        result = evaluate_cocm(args.minutes, args.month, iv)

    # Price the eligible codes under the selected payer model.
    if result.get("eligible_code"):
        codes = result["eligible_code"].split(" + ")
        total, unpriced = price_codes(codes, args.payer)
        _, confidence = get_rate(codes[0], args.payer)
        result["payer"] = args.payer
        if total is not None:
            result["estimated_payment_usd"] = f"{total:,.2f}"
            result["rate_confidence"] = confidence
        if unpriced:
            result["unpriced_codes"] = ", ".join(unpriced)

    col = 26
    for k, v in result.items():
        if v is not None:
            print(f"{k:{col}}: {v}")
    print(f"{'source_confidence':{col}}: verified_primary (CMS MLN909432; CMS-1832-F; AIMS Center)")
    print(f"{'disclaimer':{col}}: Decision-support only; verify current fee schedule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
