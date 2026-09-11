#!/usr/bin/env python3
"""cocm_time_tracker.py — CoCM / BHI midpoint-rule billing-eligibility helper.

Single source of billing truth for MedSync8: the CLI, the MCP server
(mcp/cocm_billing_server.py), the plugin, and the billing-auditor agent all
import from here. Billing RULES are data on each BillingCode (status,
mirror_of, requires_any_of, exclusive_with, payers) and are ENFORCED by
price_claim(); prose in `notes` is explanatory only.

Supported code families
-----------------------
CoCM (Collaborative Care Model):
  99492  Initial calendar month  (≥36 min, target 70)
  99493  Subsequent months       (≥31 min, target 60)
  99494  Add-on per 30-min block (≥16 min each, unlimited units)
  G2214  Shorter service         (≥30 min, base code minimum unmet)

General BHI (non-CoCM Behavioral Health Integration):
  99484  Per calendar month      (≥20 min); exclusive with 99492/99493

RHC / FQHC setting:
  G0512  DISCONTINUED 2026-01-01 — RHCs/FQHCs now report the time-based
         CoCM codes individually and may apply the midpoint rule (50%+1).

APCM companion add-ons (CY2026; require an APCM base code G0556–G0558 from
the same practitioner in the same month; Medicare-only):
  G0568  CoCM initial month      (crosswalks 99492, wRVU 1.88)
  G0569  CoCM subsequent month   (crosswalks 99493, wRVU 2.05)
  G0570  General BHI             (crosswalks 99484, wRVU 0.93)
  Finalized in CMS-1832-F (90 FR 49266 §II.G) as additions; the standalone
  codes remain active. Operating rule for the SAME patient-month: EITHER the
  G-code OR its mirror CPT code — never both. Supplement-vs-replace is
  unresolved in the CY2026 rule (NACHC: "CMS Clarification Pending"), so
  G-code billing is ON HOLD pending written MAC confirmation. Not time-based.

Valid initiating visits (required before any CoCM/BHI month):
  99202-99215, G0402, G0438, G0439, 99495, 99496, 90791, 90792

Payer rate model (--payer)
--------------------------
  medicare-natl  CY2026 national non-facility PFS
  medicare-wi    Wisconsin statewide locality estimate = national × 0.952
                 (GPCIs: work 1.000 floor, PE ~0.94 est., MP 0.331)
  wi-medicaid    ForwardHealth / BadgerCare Plus. Exact amounts are in the
                 ForwardHealth interactive Max Fee Schedule (physician
                 services) — portal lookup only. Supply real values via
                 WI_MEDICAID_RATES_JSON='{"99492": 101.50, ...}'; otherwise
                 an estimate of national × WI_MEDICAID_FACTOR (default 0.70)
                 is used and labeled `estimated`. Medicare-only codes (APCM
                 add-ons) are never estimated for Medicaid.

Sources: see SOURCES below. Decision-support only.

Usage examples
--------------
    python3 cocm_time_tracker.py --minutes 72 --month initial --initiating-visit yes --payer medicare-wi
    python3 cocm_time_tracker.py --minutes 116 --month subsequent --initiating-visit yes
    python3 cocm_time_tracker.py --mode bhi --minutes 25 --initiating-visit yes --payer wi-medicaid
    python3 cocm_time_tracker.py --list-codes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

SOURCES: tuple[str, ...] = (
    "CMS MLN909432 (Jan 2026)",
    "CMS-1832-F (90 FR 49266 §II.G)",
    "CMS MM14315 / CR 14315",
    "NACHC APCM Reimbursement Tip Sheet (Mar 2026)",
    "AIMS Center CoCM Implementation Guide",
)
SOURCE_LINE = "Source: " + " · ".join(SOURCES)
DISCLAIMER = (
    "Decision-support only. Verify against the current CMS Physician Fee "
    "Schedule and the ForwardHealth portal before claim submission."
)
# Thresholds (midpoint rule) are verified against primary CMS sources; each
# rate carries its own confidence + source on the BillingCode.
THRESHOLD_CONFIDENCE = "verified_primary (CMS MLN909432; CMS-1832-F)"

Status = Literal["active", "hold", "discontinued"]
RateConfidence = Literal["verified_secondary", "estimated", "portal_verified", ""]
Payer = Literal["medicare-natl", "medicare-wi", "wi-medicaid"]
PAYERS: tuple[str, ...] = ("medicare-natl", "medicare-wi", "wi-medicaid")
MEDICARE_PAYERS: tuple[str, ...] = ("medicare-natl", "medicare-wi")

APCM_BASE_CODES: tuple[str, ...] = ("G0556", "G0557", "G0558")
APCM_HOLD_NOTE = (
    "billing hold pending written MAC confirmation (supplement-vs-replace "
    "unresolved in CY2026 rule; NACHC: CMS Clarification Pending)"
)
G0512_DISCONTINUED_NOTE = (
    "discontinued 2026-01-01 (CY2026 final rule); RHCs/FQHCs report "
    "99492/99493/99494/G2214 individually with the midpoint rule"
)


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
    medicare_natl: float | None = None   # CY2026 national non-facility, USD
    wi_medicaid: float | None = None     # ForwardHealth portal max fee, USD
    rate_confidence: RateConfidence = ""
    rate_source: str = ""                # where the Medicare rate came from
    status: Status = "active"
    status_note: str = ""                # why hold / discontinued
    mirror_of: str | None = None         # APCM add-on ↔ CPT crosswalk
    requires_any_of: tuple[str, ...] = ()   # must appear on the same claim/month
    exclusive_with: tuple[str, ...] = ()    # never with these in the same month
    payers: tuple[str, ...] = PAYERS        # payer models that can price this code
    notes: str = ""


_MEMO = "Jul 2026 APCM memo (secondary_corroborated)"

COCM_CODES: list[BillingCode] = [
    BillingCode(
        "99492", "CoCM — initial calendar month", "CoCM",
        target_min=70, min_to_bill=36,
        medicare_natl=160.32, rate_confidence="verified_secondary", rate_source=_MEMO,
        exclusive_with=("99493", "99484", "G2214"),
        notes="First month of CoCM enrollment only. Requires patient registry, "
              "care plan, and systematic caseload review by the supervising provider.",
    ),
    BillingCode(
        "99493", "CoCM — subsequent calendar month", "CoCM",
        target_min=60, min_to_bill=31,
        medicare_natl=144.96, rate_confidence="verified_secondary", rate_source=_MEMO,
        exclusive_with=("99492", "99484", "G2214"),
        notes="Every month after the initial month.",
    ),
    BillingCode(
        "99494", "CoCM — each additional 30-min block (add-on ×N)", "CoCM",
        target_min=30, min_to_bill=16,
        medicare_natl=61.46, rate_confidence="verified_secondary", rate_source=_MEMO,
        requires_any_of=("99492", "99493"),
        notes="Add-on to 99492 or 99493. One unit per 30-min increment past the "
              "base target. No cap on number of units per month.",
    ),
    BillingCode(
        "G2214", "CoCM / BHI — shorter first- or subsequent-month service", "CoCM",
        target_min=30, min_to_bill=30,
        medicare_natl=60.79, rate_confidence="verified_secondary", rate_source=_MEMO,
        exclusive_with=("99492", "99493"),
        notes="For patients with ≥30 min who don't meet the base code minimum.",
    ),
]

BHI_CODES: list[BillingCode] = [
    BillingCode(
        "99484", "General BHI — per calendar month", "General BHI",
        target_min=20, min_to_bill=20,
        medicare_natl=57.78, rate_confidence="estimated",
        rate_source="crosswalk-derived from G0570 (same wRVU 0.93); not "
                    "independently published in the Jul 2026 memo",
        exclusive_with=("99492", "99493"),
        notes="Non-CoCM path. BHI clinical staff ≥20 min/month. No registry or "
              "systematic caseload review required.",
    ),
]

FQHC_CODES: list[BillingCode] = [
    BillingCode(
        "G0512", "RHC/FQHC psychiatric CoCM (monthly)", "RHC/FQHC",
        target_min=None, min_to_bill=None,
        status="discontinued", status_note=G0512_DISCONTINUED_NOTE,
        notes="Retained for historical (pre-2026) claims only.",
    ),
]

_NACHC = "NACHC APCM Tip Sheet (Mar 2026), CMS-derived CY2026 national non-facility"

APCM_ADDON_CODES: list[BillingCode] = [
    BillingCode(
        "G0568", "APCM add-on — CoCM initial month (crosswalks 99492, wRVU 1.88)",
        "APCM add-on", target_min=None, min_to_bill=None,
        medicare_natl=161.66, rate_confidence="verified_secondary", rate_source=_NACHC,
        status="hold", status_note=APCM_HOLD_NOTE,
        mirror_of="99492", requires_any_of=APCM_BASE_CODES, payers=MEDICARE_PAYERS,
        notes="Not time-based; distinguished from G0569 by episode month only.",
    ),
    BillingCode(
        "G0569", "APCM add-on — CoCM subsequent month (crosswalks 99493, wRVU 2.05)",
        "APCM add-on", target_min=None, min_to_bill=None,
        medicare_natl=145.96, rate_confidence="verified_secondary", rate_source=_NACHC,
        status="hold", status_note=APCM_HOLD_NOTE,
        mirror_of="99493", requires_any_of=APCM_BASE_CODES, payers=MEDICARE_PAYERS,
        notes="Not time-based.",
    ),
    BillingCode(
        "G0570", "APCM add-on — General BHI (crosswalks 99484, wRVU 0.93)",
        "APCM add-on", target_min=None, min_to_bill=None,
        medicare_natl=57.78, rate_confidence="verified_secondary", rate_source=_NACHC,
        status="hold", status_note=APCM_HOLD_NOTE,
        mirror_of="99484", requires_any_of=APCM_BASE_CODES, payers=MEDICARE_PAYERS,
        notes="General BHI model — no psychiatric consultant.",
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
        wi_medicaid=5.75, rate_confidence="portal_verified", payers=("wi-medicaid",),
        notes="ForwardHealth BHIC contract. Billed in 15-min units.",
    ),
    BillingCode(
        "S0280", "Medical home — comprehensive care coordination and planning, "
                 "initial plan", "WI Medicaid BHIC",
        target_min=None, min_to_bill=None,
        wi_medicaid=473.64, rate_confidence="portal_verified", payers=("wi-medicaid",),
        notes="ForwardHealth BHIC contract. One-time initial care plan.",
    ),
    BillingCode(
        "S0281", "Medical home — care coordination, maintenance of plan",
        "WI Medicaid BHIC",
        target_min=None, min_to_bill=None,
        wi_medicaid=13.14, rate_confidence="portal_verified", payers=("wi-medicaid",),
        notes="ForwardHealth BHIC contract. Ongoing plan maintenance.",
    ),
]

INITIATING_VISIT_CODES: list[BillingCode] = [
    BillingCode("99202-99215", "Office / outpatient E/M visit", "Initiating", None, None,
                notes="Most common. Must address the behavioral health condition."),
    BillingCode("G0402", "Welcome to Medicare preventive visit", "Initiating", None, None),
    BillingCode("G0438", "Annual Wellness Visit — initial", "Initiating", None, None),
    BillingCode("G0439", "Annual Wellness Visit — subsequent", "Initiating", None, None),
    BillingCode("99495", "Transitional Care Management — 14-day contact, moderate complexity",
                "Initiating", None, None),
    BillingCode("99496", "Transitional Care Management — 7-day contact, high complexity",
                "Initiating", None, None),
    BillingCode("90791", "Psychiatric diagnostic evaluation", "Initiating", None, None,
                notes="Common initiating visit at NEH. No medical services component."),
    BillingCode("90792", "Psychiatric diagnostic evaluation with medical services",
                "Initiating", None, None,
                notes="Includes medication management; typical for prescribing providers at NEH."),
]

ALL_CODES = (
    COCM_CODES + BHI_CODES + FQHC_CODES + APCM_ADDON_CODES
    + WI_MEDICAID_BHIC_CODES + INITIATING_VISIT_CODES
)
CODE_MAP: dict[str, BillingCode] = {c.code: c for c in ALL_CODES}
# CPT code -> its APCM add-on (derived from the catalogue, never hand-listed).
APCM_MIRROR: dict[str, str] = {c.mirror_of: c.code for c in APCM_ADDON_CODES if c.mirror_of}


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
WI_MEDICAID_FACTOR = float(os.environ.get("WI_MEDICAID_FACTOR", "0.70"))
try:
    _WI_MEDICAID_OVERRIDES: dict[str, float] = {
        k: float(v)
        for k, v in json.loads(os.environ.get("WI_MEDICAID_RATES_JSON", "{}")).items()
    }
except (json.JSONDecodeError, TypeError, ValueError):
    print("warning: WI_MEDICAID_RATES_JSON is not valid JSON — ignoring", file=sys.stderr)
    _WI_MEDICAID_OVERRIDES = {}


@dataclass(frozen=True)
class RateInfo:
    code: str
    payer: str
    rate_usd: float | None
    confidence: RateConfidence
    status: Status | Literal["unknown"]
    source: str
    note: str   # human explanation: why None, how estimated, hold/discontinued


def rate_info(code: str, payer: str) -> RateInfo:
    """Resolve a code's rate under a payer model with full provenance."""
    if payer not in PAYERS:
        raise ValueError(f"unknown payer: {payer}")
    bc = CODE_MAP.get(code)
    if bc is None:
        return RateInfo(code, payer, None, "", "unknown", "", "unknown code")
    if bc.status == "discontinued":
        return RateInfo(code, payer, None, "", bc.status, "", bc.status_note)
    if payer not in bc.payers:
        return RateInfo(code, payer, None, "", bc.status, "",
                        f"not covered under {payer}")

    hold = f"; {bc.status_note}" if bc.status == "hold" else ""

    if payer == "wi-medicaid":
        if code in _WI_MEDICAID_OVERRIDES:
            return RateInfo(code, payer, _WI_MEDICAID_OVERRIDES[code], "portal_verified",
                            bc.status, "WI_MEDICAID_RATES_JSON override",
                            "ForwardHealth portal value supplied by operator" + hold)
        if bc.wi_medicaid is not None:
            return RateInfo(code, payer, bc.wi_medicaid, "portal_verified", bc.status,
                            "ForwardHealth BHIC contract extract",
                            "ForwardHealth portal value" + hold)
        if bc.medicare_natl is None:
            return RateInfo(code, payer, None, "", bc.status, "", "not modeled")
        return RateInfo(
            code, payer, round(bc.medicare_natl * WI_MEDICAID_FACTOR, 2), "estimated",
            bc.status, f"national × WI_MEDICAID_FACTOR ({WI_MEDICAID_FACTOR:.0%})",
            "UNVERIFIED estimate — set WI_MEDICAID_RATES_JSON with ForwardHealth "
            "portal values" + hold,
        )

    if bc.medicare_natl is None:
        return RateInfo(code, payer, None, "", bc.status, "", "not modeled")
    if payer == "medicare-natl":
        return RateInfo(code, payer, bc.medicare_natl, bc.rate_confidence, bc.status,
                        bc.rate_source, "CY2026 national non-facility" + hold)
    # medicare-wi
    return RateInfo(
        code, payer, round(bc.medicare_natl * WI_GPCI_FACTOR, 2), "estimated", bc.status,
        f"national × WI_GPCI_FACTOR ({WI_GPCI_FACTOR})",
        "GPCI-adjusted estimate; confirm via NGS J6 fee lookup" + hold,
    )


def get_rate(code: str, payer: str) -> tuple[float | None, str]:
    """Compatibility wrapper: (rate_usd, confidence_label)."""
    info = rate_info(code, payer)
    return info.rate_usd, info.confidence


@dataclass
class ClaimPricing:
    payer: str
    lines: list[RateInfo] = field(default_factory=list)
    total_usd: float | None = None
    unpriced_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def claim_warnings(codes: list[str]) -> list[str]:
    """Rule checks that hold regardless of payer: status, prerequisites, exclusivity."""
    present = set(codes)
    warnings: list[str] = []
    seen_pairs: set[frozenset[str]] = set()
    for c in dict.fromkeys(codes):  # preserve order, dedupe
        bc = CODE_MAP.get(c)
        if bc is None:
            warnings.append(f"{c}: unknown code")
            continue
        if bc.status == "discontinued":
            warnings.append(f"{c}: {bc.status_note}")
        elif bc.status == "hold":
            warnings.append(f"{c}: {bc.status_note}")
        if bc.requires_any_of and not present.intersection(bc.requires_any_of):
            warnings.append(
                f"{c}: requires one of {'/'.join(bc.requires_any_of)} on the same claim/month"
            )
        conflicts = set(bc.exclusive_with)
        if bc.mirror_of:
            conflicts.add(bc.mirror_of)
        for other in sorted(conflicts & present):
            pair = frozenset({c, other})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            reason = ("same work (APCM crosswalk) — duplicate-service audit risk"
                      if bc.mirror_of == other or CODE_MAP[other].mirror_of == c
                      else "mutually exclusive in the same calendar month")
            warnings.append(f"{c} + {other}: never both for the same patient-month — {reason}")
    return warnings


def price_claim(codes: list[str], payer: str) -> ClaimPricing:
    """Price a billed code list under a payer, enforcing catalogue rules."""
    pricing = ClaimPricing(payer=payer, warnings=claim_warnings(codes))
    total = 0.0
    priced_any = False
    for c in codes:
        info = rate_info(c, payer)
        pricing.lines.append(info)
        if info.rate_usd is None:
            pricing.unpriced_codes.append(c)
        else:
            total += info.rate_usd
            priced_any = True
    pricing.total_usd = round(total, 2) if priced_any else None
    return pricing


def price_codes(codes: list[str], payer: str) -> tuple[float | None, list[str]]:
    """Compatibility wrapper: (total_usd, unpriced_codes). Prefer price_claim()."""
    p = price_claim(codes, payer)
    return p.total_usd, p.unpriced_codes


# ---------------------------------------------------------------------------
# Eligibility logic
# ---------------------------------------------------------------------------

def _apcm_alternative(base_code: str) -> str | None:
    g = APCM_MIRROR.get(base_code)
    if g is None:
        return None
    bc = CODE_MAP[g]
    return (
        f"{g} — APCM-enrolled patients only ({'/'.join(APCM_BASE_CODES)}); "
        f"either/or with {base_code}, never both in the same month; {bc.status_note}"
    )


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
        apcm_alternative=_apcm_alternative(base_code),
        note="Midpoint rule satisfied for base code.",
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
            apcm_alternative=_apcm_alternative("99484"),
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
    "APCM add-on": f"APCM Companion Add-ons (CY2026 — require {'/'.join(APCM_BASE_CODES)})",
    "WI Medicaid BHIC": "WI Medicaid BHIC Contract (ForwardHealth portal — verified)",
    "Initiating":  "Valid Initiating Visit Codes (required before first CoCM/BHI month)",
}


def _wrap(text: str, width: int = 60) -> list[str]:
    lines, line, col = [], [], 0
    for w in text.split():
        if col + len(w) + 1 > width and line:
            lines.append(" ".join(line))
            line, col = [w], len(w)
        else:
            line.append(w)
            col += len(w) + 1
    if line:
        lines.append(" ".join(line))
    return lines


def print_code_catalogue() -> None:
    by_cat: dict[str, list[BillingCode]] = {c: [] for c in _CATEGORY_ORDER}
    for code in ALL_CODES:
        by_cat[code.category].append(code)

    for cat in _CATEGORY_ORDER:
        print(f"\n{'─' * 72}")
        print(f"  {_CATEGORY_LABELS[cat]}")
        print(f"{'─' * 72}")
        for c in by_cat[cat]:
            time_info = ""
            if c.min_to_bill is not None and c.target_min is not None:
                time_info = f"  [≥{c.min_to_bill}–{c.target_min} min]"
            elif c.min_to_bill is not None:
                time_info = f"  [≥{c.min_to_bill} min]"
            tag = f"  [{c.status.upper()}]" if c.status != "active" else ""
            print(f"  {c.code:<14}  {c.description}{time_info}{tag}")
            details = []
            if c.status != "active":
                details.append(c.status_note)
            if c.exclusive_with:
                details.append("Exclusive with " + ", ".join(c.exclusive_with) + " in the same month.")
            if c.requires_any_of:
                details.append("Requires " + "/".join(c.requires_any_of) + " on the same claim.")
            if c.notes:
                details.append(c.notes)
            for d in details:
                for ln in _wrap(d):
                    print(f"  {'':14}  ↳ {ln}")


def print_rate_table() -> None:
    print(f"\n{'─' * 72}")
    print("  Rate table (USD per unit — decision-support estimates)")
    print(f"{'─' * 72}")
    print(f"  {'Code':<8}{'Medicare natl':>14}{'Medicare WI*':>14}{'WI Medicaid**':>15}  Status")
    for c in COCM_CODES + BHI_CODES + APCM_ADDON_CODES + FQHC_CODES + WI_MEDICAID_BHIC_CODES:
        cells = []
        for payer in PAYERS:
            info = rate_info(c.code, payer)
            if info.rate_usd is None:
                cells.append("—")
            else:
                mark = {"estimated": "~", "verified_secondary": "", "portal_verified": ""}[info.confidence]
                cells.append(f"{info.rate_usd:,.2f}{mark}")
        status = "" if c.status == "active" else c.status.upper()
        print(f"  {c.code:<8}{cells[0]:>14}{cells[1]:>14}{cells[2]:>15}  {status}")
    print(
        "\n  ~  estimated (GPCI-adjusted, crosswalk-derived, or WI_MEDICAID_FACTOR"
        f" {WI_MEDICAID_FACTOR:.0%}) — UNVERIFIED.\n"
        "  *  WI = national × 0.952 (GPCI est.: work 1.000, PE ~0.94, MP 0.331);\n"
        "     statewide locality, MAC = NGS Jurisdiction 6 (contract 06302).\n"
        "  ** ForwardHealth interactive Max Fee Schedule is authoritative (physician\n"
        "     services — not per-program PDFs); supply via WI_MEDICAID_RATES_JSON.\n"
        "     Medicare-only codes (APCM add-ons) are never estimated for Medicaid.\n"
        "  HOLD/DISCONTINUED codes are flagged by price_claim() warnings.\n"
        "  Sequestration not applied."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="CoCM / BHI midpoint-rule billing eligibility (decision-support only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"{SOURCE_LINE}\nDisclaimer: {DISCLAIMER}",
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
        print(f"\n{SOURCE_LINE}\nDisclaimer: {DISCLAIMER}")
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
        pricing = price_claim(result["eligible_code"].split(" + "), args.payer)
        first = pricing.lines[0]
        result["payer"] = args.payer
        if pricing.total_usd is not None:
            result["estimated_payment_usd"] = f"{pricing.total_usd:,.2f}"
            result["rate_confidence"] = first.confidence
            result["rate_source"] = first.source
        if pricing.unpriced_codes:
            result["unpriced_codes"] = ", ".join(pricing.unpriced_codes)
        if pricing.warnings:
            result["warnings"] = " | ".join(pricing.warnings)

    col = 26
    for k, v in result.items():
        if v is not None:
            print(f"{k:{col}}: {v}")
    print(f"{'threshold_confidence':{col}}: {THRESHOLD_CONFIDENCE}")
    print(f"{'sources':{col}}: {' · '.join(SOURCES)}")
    print(f"{'disclaimer':{col}}: {DISCLAIMER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
