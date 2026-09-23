#!/usr/bin/env python3
"""cocm_time_tracker.py — CoCM / BHI midpoint-rule billing-eligibility helper.

Single source of billing truth for MedSync8: the CLI, the MCP server
(mcp/cocm_billing_server.py), the plugin, and the billing-auditor agent all
import from here. Billing RULES are data on each BillingCode (status,
mirror_of, requires_any_of, exclusive_with, payers) and are ENFORCED by
price_claim(); prose in `notes` is explanatory only. RATES are data too:
every (code, payer) rate is an explicit `Rate` with its own confidence label
and source locator — nothing is derived from a factor.

Supported code families
-----------------------
CoCM (Collaborative Care Model):
  99492  Initial calendar month  (≥36 min, target 70)
  99493  Subsequent months       (≥31 min, target 60)
  99494  Add-on per 30-min block (≥16 min each, unlimited units)
  G2214  Shorter service         (≥30 min, base code minimum unmet)
         Medicare-only: absent from every ForwardHealth (WI Medicaid)
         schedule (verifications 2026-07-30 and 2026-09-05).

General BHI (non-CoCM Behavioral Health Integration):
  99484  Per calendar month      (≥20 min); exclusive with 99492/99493

RHC / FQHC setting:
  G0512  DISCONTINUED 2026-01-01 — RHCs/FQHCs now report the time-based
         CoCM codes individually and may apply the midpoint rule (50%+1).
         ForwardHealth end-dated G0511/G0512 on 2025-12-31 as well (Update
         2026-07); CHCs bill the CPT codes under Online Handbook #22557.

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

Payer rate models (--payer)
---------------------------
  medicare-wi    Medicare PFS, Wisconsin locality (WI:00; MAC NGS J6,
                 contract 06302), non-facility, non-QP. Computed from the
                 CMS CY2026 RVU/GPCI release (work 1.000 / PE 0.958 /
                 MP 0.308; CF 33.4009). Office billing practitioner.
  medicare-fqhc  CMS CY2026 designated RHC/FQHC care-coordination rates
                 (national non-facility; not the WI office locality).
  wi-medicaid    ForwardHealth / BadgerCare Plus fee-for-service maximum
                 allowable fees (official 2026-09-05 max-fee snapshot,
                 physician services). Rendering provider type and POS must
                 match. A psychiatrist cannot be the Wisconsin CoCM billing
                 practitioner (consultant role only). CHCs use the T1015
                 PPS pathway instead of these fees.

Rate provenance labels (weakest line governs a claim):
  portal_verified    this practice's contract / portal extract
  verified_primary   read or computed directly from the payer's published
                     primary file (CMS RVU release, CMS FQHC rate file,
                     ForwardHealth max-fee snapshot) — file and date recorded
  verified_secondary a dated secondary document citing the primary file
  estimated          crosswalk- or factor-derived — UNVERIFIED

Overrides: RATE_OVERRIDES_JSON='{"wi-medicaid": {"99484": {"usd": 41.28,
"confidence": "portal_verified", "source": "ForwardHealth query 2026-09-21"}}}'
(a bare number is accepted and labeled portal_verified). The legacy
WI_MEDICAID_RATES_JSON='{"99484": 41.28}' shorthand still works.

Sources: see SOURCES below. Decision-support only.

Usage examples
--------------
    python3 cocm_time_tracker.py --minutes 72 --month initial --initiating-visit yes --payer medicare-wi
    python3 cocm_time_tracker.py --minutes 116 --month subsequent --initiating-visit yes --payer medicare-fqhc
    python3 cocm_time_tracker.py --mode bhi --minutes 25 --initiating-visit yes --payer wi-medicaid
    python3 cocm_time_tracker.py --capacity-plan 125 --payer-mix wi-medicaid=0.7,medicare-wi=0.1,private=0.2
    python3 cocm_time_tracker.py --list-codes
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

SOURCES: tuple[str, ...] = (
    "CMS MLN909432 (Jan 2026)",
    "CMS-1832-F (90 FR 49266 §II.G)",
    "CMS MM14315 / CR 14315",
    "CMS CY2026 PFS RVU file RVU26C (updated 2026-06-30)",
    "CMS RHC/FQHC CY2026 non-facility payment rates",
    "ForwardHealth max-fee snapshot MEDSV 2026-09-05",
    "ForwardHealth Update 2026-07 (Mar 2026)",
    "NEH CoCM consolidated workbook (2026-09-20)",
    "NEH WI CoCM rate verification memo V1.0 (2026-09-07)",
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
RateConfidence = Literal[
    "portal_verified", "verified_primary", "verified_secondary", "estimated", ""
]
RATE_CONFIDENCE_LEVELS: tuple[str, ...] = (
    "portal_verified", "verified_primary", "verified_secondary", "estimated"
)
# Lower rank = stronger. A claim is only as verified as its weakest line.
_CONFIDENCE_RANK: dict[str, int] = {
    "portal_verified": 0, "verified_primary": 1, "verified_secondary": 2,
    "estimated": 3, "": 4,
}

Payer = Literal["medicare-wi", "medicare-fqhc", "wi-medicaid"]
PAYERS: tuple[str, ...] = ("medicare-wi", "medicare-fqhc", "wi-medicaid")
MEDICARE_PAYERS: tuple[str, ...] = ("medicare-wi", "medicare-fqhc")
RETIRED_PAYERS: dict[str, str] = {
    # old name -> why / what replaced it
    "medicare-natl": (
        "retired 2026-09-20: its figures were the CMS FQHC designated rates, "
        "now modeled as medicare-fqhc; office billing uses medicare-wi"
    ),
}


@dataclass(frozen=True)
class PayerModel:
    payer: str
    description: str
    source: str
    caveat: str


PAYER_MODELS: dict[str, PayerModel] = {
    "medicare-wi": PayerModel(
        "medicare-wi",
        "Medicare PFS, Wisconsin locality (WI:00), non-facility, non-QP",
        "CMS CY2026 RVU/GPCI release; GPCI work 1.000 / PE 0.958 / MP 0.308; "
        "CF 33.4009; MAC NGS Jurisdiction 6 (contract 06302)",
        "Computed PFS allowables. Confirm with the MAC before claim submission. "
        "Sequestration not applied.",
    ),
    "medicare-fqhc": PayerModel(
        "medicare-fqhc",
        "CMS CY2026 designated RHC/FQHC care-coordination rates (national non-facility)",
        "CMS RHC/FQHC CY2026 non-facility payment rates file",
        "Separately priced FQHC care-coordination pathway, not the WI office "
        "locality and not an FQHC PPS encounter.",
    ),
    "wi-medicaid": PayerModel(
        "wi-medicaid",
        "ForwardHealth / BadgerCare Plus fee-for-service maximum allowable fee",
        "ForwardHealth interactive max-fee schedule, official snapshot "
        "MEDSV_max_fee_20260905.csv (physician services)",
        "Rendering provider type / POS must match. A psychiatrist cannot be the "
        "WI CoCM billing practitioner (consultant only; Online Handbook #22557). "
        "CHCs bill CoCM through the T1015 PPS pathway, not these fees. HMOs must "
        "cover at least the fee-for-service benefit (Update 2026-07).",
    ),
}

APCM_BASE_CODES: tuple[str, ...] = ("G0556", "G0557", "G0558")
APCM_HOLD_NOTE = (
    "billing hold pending written MAC confirmation (supplement-vs-replace "
    "unresolved in CY2026 rule; NACHC: CMS Clarification Pending)"
)
G0512_DISCONTINUED_NOTE = (
    "discontinued 2026-01-01 (CY2026 final rule; ForwardHealth end-dated "
    "G0511/G0512 2025-12-31); RHCs/FQHCs report 99492/99493/99494/G2214 "
    "individually with the midpoint rule"
)


# ---------------------------------------------------------------------------
# Rate data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rate:
    usd: float
    confidence: RateConfidence
    source: str          # file / document the amount was read or computed from
    note: str = ""       # scope limits (locality, POS, provider type…)


# Source locators. Each names the primary file (with release/date) and the
# NEH document in which it was read or computed — never a bare "memo".
_WB = "NEH-CoCM-Spravato-FQHC-Consolidated-2026-09-20.xlsx (Rates sheet)"
_MEMO = "NEH-WI-Memo-CoCM-Rate-Verification-V1.0 (2026-09-07), §2 grid"
SRC_CMS_RVU26C = (
    "CMS CY2026 PFS RVU26C (rvu26c-updated-06-30-2026.zip), WI locality 00 "
    f"non-facility, CF 33.4009 — computed in {_WB}"
)
SRC_CMS_RVU26A = (
    "CMS CY2026 PFS RVU26A (January release), WI locality 00 non-facility, "
    f"CF 33.4009 — computed in {_MEMO}; re-verify against RVU26C"
)
SRC_CMS_FQHC = (
    "CMS RHC/FQHC CY2026 non-facility payment rates "
    f"(rhc-fqhc-cy-2026-non-facility-payment-rates.zip) — read in {_WB}"
)
SRC_FH_20260905 = (
    "ForwardHealth MEDSV_max_fee_20260905.csv (official 2026-09-05 snapshot, "
    f"physician services) — read in {_WB}"
)
SRC_FH_BHIC = "ForwardHealth BHIC contract extract (eff. 2014-04-01, provider types 11/801-803)"
SRC_NACHC = "NACHC APCM Reimbursement Tip Sheet (Mar 2026), CMS-derived CY2026 national non-facility"

_WI_OFFICE = "WI locality office allowable; non-FQHC billing practitioner"
_FQHC_NOTE = "national FQHC care-coordination rate; not the WI office locality"
_WI_MCD = "FFS maximum allowable fee; CHCs use the T1015 PPS pathway instead"


def _rates(**by_payer: Rate) -> dict[str, Rate]:
    """Build a rate map keyed by payer id (kwargs use '_' for '-')."""
    return {k.replace("_", "-"): v for k, v in by_payer.items()}


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
    rates: Mapping[str, Rate] = field(default_factory=dict)  # payer -> Rate
    status: Status = "active"
    status_note: str = ""                # why hold / discontinued
    mirror_of: str | None = None         # APCM add-on ↔ CPT crosswalk
    requires_any_of: tuple[str, ...] = ()   # must appear on the same claim/month
    exclusive_with: tuple[str, ...] = ()    # never with these in the same month
    payers: tuple[str, ...] = PAYERS        # payer models that can price this code
    notes: str = ""


COCM_CODES: list[BillingCode] = [
    BillingCode(
        "99492", "CoCM — initial calendar month", "CoCM",
        target_min=70, min_to_bill=36,
        rates=_rates(
            medicare_wi=Rate(153.19, "verified_primary", SRC_CMS_RVU26C, _WI_OFFICE),
            medicare_fqhc=Rate(160.32, "verified_primary", SRC_CMS_FQHC, _FQHC_NOTE),
            wi_medicaid=Rate(146.05, "verified_primary", SRC_FH_20260905, _WI_MCD),
        ),
        exclusive_with=("99493", "99484", "G2214"),
        notes="First month of CoCM enrollment only. Requires patient registry, "
              "care plan, and systematic caseload review by the supervising provider.",
    ),
    BillingCode(
        "99493", "CoCM — subsequent calendar month", "CoCM",
        target_min=60, min_to_bill=31,
        rates=_rates(
            medicare_wi=Rate(138.71, "verified_primary", SRC_CMS_RVU26C, _WI_OFFICE),
            medicare_fqhc=Rate(144.96, "verified_primary", SRC_CMS_FQHC, _FQHC_NOTE),
            wi_medicaid=Rate(141.61, "verified_primary", SRC_FH_20260905, _WI_MCD),
        ),
        exclusive_with=("99492", "99484", "G2214"),
        notes="Every month after the initial month.",
    ),
    BillingCode(
        "99494", "CoCM — each additional 30-min block (add-on ×N)", "CoCM",
        target_min=30, min_to_bill=16,
        rates=_rates(
            medicare_wi=Rate(58.72, "verified_primary", SRC_CMS_RVU26C, _WI_OFFICE),
            medicare_fqhc=Rate(61.46, "verified_primary", SRC_CMS_FQHC, _FQHC_NOTE),
            wi_medicaid=Rate(60.51, "verified_primary", SRC_FH_20260905,
                             _WI_MCD + "; no added PPS encounter for an extra unit"),
        ),
        requires_any_of=("99492", "99493"),
        notes="Add-on to 99492 or 99493. One unit per 30-min increment past the "
              "base target. No cap on number of units per month.",
    ),
    BillingCode(
        "G2214", "CoCM / BHI — shorter first- or subsequent-month service", "CoCM",
        target_min=30, min_to_bill=30,
        rates=_rates(
            medicare_wi=Rate(58.01, "verified_secondary", SRC_CMS_RVU26A, _WI_OFFICE),
        ),
        exclusive_with=("99492", "99493"),
        payers=MEDICARE_PAYERS,
        notes="For patients with ≥30 min who don't meet the base code minimum. "
              "Absent from every ForwardHealth schedule (verified 2026-07-30 and "
              "2026-09-05): CoCM months under the base minimum are non-billable to "
              "WI Medicaid — track as unbilled care-manager time.",
    ),
]

BHI_CODES: list[BillingCode] = [
    BillingCode(
        "99484", "General BHI — per calendar month", "General BHI",
        target_min=20, min_to_bill=20,
        rates=_rates(
            medicare_wi=Rate(55.04, "verified_secondary", SRC_CMS_RVU26A, _WI_OFFICE),
        ),
        exclusive_with=("99492", "99493"),
        notes="Non-CoCM path. BHI clinical staff ≥20 min/month. No registry or "
              "systematic caseload review required. WI Medicaid fee not in the "
              "2026-09-05 verification set (prior finding ~75% of Medicare, "
              "2026-07-30) — query ForwardHealth and load via RATE_OVERRIDES_JSON.",
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

APCM_ADDON_CODES: list[BillingCode] = [
    BillingCode(
        "G0568", "APCM add-on — CoCM initial month (crosswalks 99492, wRVU 1.88)",
        "APCM add-on", target_min=None, min_to_bill=None,
        rates=_rates(
            medicare_wi=Rate(154.25, "verified_secondary", SRC_CMS_RVU26A,
                             _WI_OFFICE + "; NACHC national figure 161.66 (" + SRC_NACHC + ")"),
        ),
        status="hold", status_note=APCM_HOLD_NOTE,
        mirror_of="99492", requires_any_of=APCM_BASE_CODES, payers=MEDICARE_PAYERS,
        notes="Not time-based; distinguished from G0569 by episode month only.",
    ),
    BillingCode(
        "G0569", "APCM add-on — CoCM subsequent month (crosswalks 99493, wRVU 2.05)",
        "APCM add-on", target_min=None, min_to_bill=None,
        rates=_rates(
            medicare_wi=Rate(139.45, "verified_secondary", SRC_CMS_RVU26A,
                             _WI_OFFICE + "; NACHC national figure 145.96 (" + SRC_NACHC + ")"),
        ),
        status="hold", status_note=APCM_HOLD_NOTE,
        mirror_of="99493", requires_any_of=APCM_BASE_CODES, payers=MEDICARE_PAYERS,
        notes="Not time-based.",
    ),
    BillingCode(
        "G0570", "APCM add-on — General BHI (crosswalks 99484, wRVU 0.93)",
        "APCM add-on", target_min=None, min_to_bill=None,
        rates=_rates(
            medicare_wi=Rate(55.36, "verified_secondary", SRC_CMS_RVU26A,
                             _WI_OFFICE + "; NACHC national figure 57.78 (" + SRC_NACHC + ")"),
        ),
        status="hold", status_note=APCM_HOLD_NOTE,
        mirror_of="99484", requires_any_of=APCM_BASE_CODES, payers=MEDICARE_PAYERS,
        notes="General BHI model — no psychiatric consultant.",
    ),
]

# APCM base codes — catalogued so claim_warnings() recognizes a correctly
# formed APCM claim (G-code + base). APCM valuation is out of scope: no rate.
APCM_BASE_CODE_ENTRIES: list[BillingCode] = [
    BillingCode("G0556", "APCM — one or fewer chronic conditions, per month", "APCM base",
                None, None, payers=MEDICARE_PAYERS,
                notes="Prerequisite base code for G0568–G0570. Rate not modeled."),
    BillingCode("G0557", "APCM — two or more chronic conditions, per month", "APCM base",
                None, None, payers=MEDICARE_PAYERS,
                notes="Prerequisite base code for G0568–G0570. Rate not modeled."),
    BillingCode("G0558", "APCM — QMB with two or more chronic conditions, per month",
                "APCM base", None, None, payers=MEDICARE_PAYERS,
                notes="Prerequisite base code for G0568–G0570. Rate not modeled."),
]

# ForwardHealth BHIC contract rows (portal extract, effective 2014-04-01,
# no end date; provider types 11/801-803; rate type MAXFEE). This is WI
# Medicaid's integrated-care billing pathway — distinct from the CPT CoCM
# family.
WI_MEDICAID_BHIC_CODES: list[BillingCode] = [
    BillingCode(
        "H0038", "Self-help / peer services, per 15 min", "WI Medicaid BHIC",
        target_min=15, min_to_bill=15,
        rates=_rates(wi_medicaid=Rate(5.75, "portal_verified", SRC_FH_BHIC)),
        payers=("wi-medicaid",),
        notes="ForwardHealth BHIC contract. Billed in 15-min units.",
    ),
    BillingCode(
        "S0280", "Medical home — comprehensive care coordination and planning, "
                 "initial plan", "WI Medicaid BHIC",
        target_min=None, min_to_bill=None,
        rates=_rates(wi_medicaid=Rate(473.64, "portal_verified", SRC_FH_BHIC)),
        payers=("wi-medicaid",),
        notes="ForwardHealth BHIC contract. One-time initial care plan.",
    ),
    BillingCode(
        "S0281", "Medical home — care coordination, maintenance of plan",
        "WI Medicaid BHIC",
        target_min=None, min_to_bill=None,
        rates=_rates(wi_medicaid=Rate(13.14, "portal_verified", SRC_FH_BHIC)),
        payers=("wi-medicaid",),
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
    COCM_CODES + BHI_CODES + FQHC_CODES + APCM_ADDON_CODES + APCM_BASE_CODE_ENTRIES
    + WI_MEDICAID_BHIC_CODES + INITIATING_VISIT_CODES
)
CODE_MAP: dict[str, BillingCode] = {c.code: c for c in ALL_CODES}
# CPT code -> its APCM add-on (derived from the catalogue, never hand-listed).
APCM_MIRROR: dict[str, str] = {c.mirror_of: c.code for c in APCM_ADDON_CODES if c.mirror_of}


# ---------------------------------------------------------------------------
# Operator overrides (payer -> code -> Rate)
# ---------------------------------------------------------------------------

def _parse_overrides(env: Mapping[str, str]) -> dict[str, dict[str, Rate]]:
    """Read RATE_OVERRIDES_JSON (per payer) and the legacy WI_MEDICAID_RATES_JSON.

    Malformed input is ignored with a warning — an override can only add or
    replace a rate, never silently poison the table.
    """
    out: dict[str, dict[str, Rate]] = {p: {} for p in PAYERS}

    def _put(payer: str, code: str, spec: Any, var: str) -> None:
        if payer not in PAYERS:
            print(f"warning: {var}: unknown payer {payer!r} — ignoring", file=sys.stderr)
            return
        try:
            if isinstance(spec, Mapping):
                conf = str(spec.get("confidence", "portal_verified"))
                if conf not in RATE_CONFIDENCE_LEVELS:
                    raise ValueError(f"confidence must be one of {RATE_CONFIDENCE_LEVELS}")
                rate = Rate(float(spec["usd"]), conf,  # type: ignore[arg-type]
                            str(spec.get("source") or f"{var} override"),
                            str(spec.get("note", "operator-supplied value")))
            else:
                rate = Rate(float(spec), "portal_verified", f"{var} override",
                            "operator-supplied portal value")
        except (KeyError, TypeError, ValueError) as exc:
            print(f"warning: {var}: bad entry for {payer}/{code}: {exc} — ignoring",
                  file=sys.stderr)
            return
        out[payer][str(code)] = rate

    for var, wrap in (("WI_MEDICAID_RATES_JSON", True), ("RATE_OVERRIDES_JSON", False)):
        raw = env.get(var, "")
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if not isinstance(data, Mapping):
                raise TypeError("top level must be an object")
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"warning: {var} is not valid JSON ({exc}) — ignoring", file=sys.stderr)
            continue
        if wrap:
            data = {"wi-medicaid": data}
        for payer, codes in data.items():
            if not isinstance(codes, Mapping):
                print(f"warning: {var}: {payer} must map codes to rates — ignoring",
                      file=sys.stderr)
                continue
            for code, spec in codes.items():
                _put(str(payer), str(code), spec, var)
    return out


RATE_OVERRIDES: dict[str, dict[str, Rate]] = _parse_overrides(os.environ)


# ---------------------------------------------------------------------------
# Payer rate resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RateInfo:
    code: str
    payer: str
    rate_usd: float | None
    confidence: RateConfidence
    status: Status | Literal["unknown"]
    source: str
    note: str   # human explanation: why None, scope limits, hold/discontinued


def _check_payer(payer: str) -> None:
    if payer in PAYERS:
        return
    if payer in RETIRED_PAYERS:
        raise ValueError(f"payer {payer!r} {RETIRED_PAYERS[payer]}")
    raise ValueError(f"unknown payer: {payer} (choose from {', '.join(PAYERS)})")


def rate_info(code: str, payer: str) -> RateInfo:
    """Resolve a code's rate under a payer model with full provenance."""
    _check_payer(payer)
    bc = CODE_MAP.get(code)
    if bc is None:
        return RateInfo(code, payer, None, "", "unknown", "", "unknown code")
    if bc.status == "discontinued":
        return RateInfo(code, payer, None, "", bc.status, "", bc.status_note)
    if payer not in bc.payers:
        why = bc.notes if payer == "wi-medicaid" and code == "G2214" else ""
        return RateInfo(code, payer, None, "", bc.status, "",
                        f"not covered under {payer}" + (f" — {why}" if why else ""))

    hold = f"; {bc.status_note}" if bc.status == "hold" else ""
    rate = RATE_OVERRIDES[payer].get(code) or bc.rates.get(payer)
    if rate is None:
        return RateInfo(
            code, payer, None, "", bc.status, "",
            f"not in the {payer} verification set — supply via RATE_OVERRIDES_JSON"
            + (f" ({bc.notes})" if bc.category == "APCM base" else "") + hold,
        )
    return RateInfo(code, payer, rate.usd, rate.confidence, bc.status, rate.source,
                    (rate.note or PAYER_MODELS[payer].description) + hold)


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

    @property
    def confidence(self) -> RateConfidence:
        """Weakest confidence among priced lines — a claim is only as verified as its least-verified line."""
        priced = [ln for ln in self.lines if ln.rate_usd is not None]
        if not priced:
            return ""
        return max((ln.confidence for ln in priced), key=lambda c: _CONFIDENCE_RANK[c])

    @property
    def sources(self) -> str:
        return " | ".join(dict.fromkeys(ln.source for ln in self.lines if ln.rate_usd is not None))


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
    _check_payer(payer)
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


APCM_GATE_POLICY = (
    "practice policy, stricter than CMS-1832-F (which sets no minute requirement "
    "for the APCM add-ons); revisit when written MAC confirmation arrives"
)


def _apcm_gate_text(base_code: str) -> str:
    bc = CODE_MAP[base_code]
    kind = "minimum" if base_code == "99484" else "midpoint minimum"
    return f"the {base_code} {kind} ({bc.min_to_bill} min)"


def _apcm_path(base_code: str, cpt_codes: list[str]) -> dict[str, Any]:
    """Result fields for an APCM-enrolled patient: the G-code add-on instead of the CPT set."""
    g = APCM_MIRROR[base_code]
    addon = "" if base_code == "99484" else " No 99494 units on this pathway."
    return {
        "eligible_code": g,
        "cpt_alternative": " + ".join(cpt_codes),
        "note": (
            f"APCM-enrolled: {g} is the monthly add-on to the APCM base code "
            f"({'/'.join(APCM_BASE_CODES)}), which must be on the same claim. Not "
            f"time-based.{addon} Gated on {_apcm_gate_text(base_code)} as "
            f"{APCM_GATE_POLICY}. Never also report {base_code} this month. "
            f"{CODE_MAP[g].status_note}."
        ),
    }


def evaluate_cocm(
    minutes: int, month: str, initiating_visit: bool, apcm_enrolled: bool = False
) -> dict[str, Any]:
    """Return the highest supported CoCM code set for the given month's minutes.

    apcm_enrolled=True selects the APCM add-on pathway (G0568/G0569) for
    patients receiving Advanced Primary Care Management from the same
    practitioner; the CPT set is returned as cpt_alternative.
    """
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
    result: dict[str, Any] = {
        "mode": "CoCM (APCM pathway)" if apcm_enrolled else "CoCM",
        "accrued_minutes": minutes,
        "month": month,
    }

    if minutes < base_min:
        if minutes >= 30:
            result.update(
                eligible_code="G2214",
                note=(
                    f"Base {base_code} minimum ({base_min} min) unmet. "
                    f"{minutes} min qualifies for G2214 (≥30-min shorter service; "
                    "Medicare-only — not billable to WI Medicaid)."
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
        if apcm_enrolled:
            result["note"] += (
                f" APCM-enrolled, but {APCM_MIRROR[base_code]} is gated on "
                f"{_apcm_gate_text(base_code)} ({APCM_GATE_POLICY}) and is not "
                "recommended this month. Whether G2214 may be reported in an APCM "
                "month is unresolved — confirm with the MAC."
            )
        return result

    # Base code met — tally add-on 99494 units.
    extra = minutes - target
    addon_units = 0
    if extra >= 16:
        addon_units = 1 + max(0, (extra - 16) // 30)

    codes = [base_code] + ["99494"] * addon_units
    next_threshold = target + 16 + addon_units * 30

    if apcm_enrolled:
        result.update(base_min_met=True, **_apcm_path(base_code, codes))
        return result

    result.update(
        eligible_code=" + ".join(codes),
        base_min_met=True,
        addon_30min_units=addon_units,
        next_99494_at_min=(next_threshold if minutes < next_threshold else None),
        apcm_alternative=_apcm_alternative(base_code),
        note="Midpoint rule satisfied for base code.",
    )
    return result


def evaluate_bhi(
    minutes: int, initiating_visit: bool, apcm_enrolled: bool = False
) -> dict[str, Any]:
    """Return eligibility for General BHI (99484), or G0570 when apcm_enrolled."""
    result: dict[str, Any] = {
        "mode": "General BHI (APCM pathway)" if apcm_enrolled else "General BHI (non-CoCM)",
        "accrued_minutes": minutes,
    }

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
        if apcm_enrolled:
            result.update(_apcm_path("99484", ["99484"]))
            return result
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
            note=f"{minutes} min does not meet the ≥20-min minimum for 99484."
            + (f" APCM-enrolled, but G0570 is gated on {_apcm_gate_text('99484')} "
               f"({APCM_GATE_POLICY}) and is not recommended this month."
               if apcm_enrolled else ""),
        )
    return result


# ---------------------------------------------------------------------------
# Capacity planning (billing side only — no labor/cost modeling)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanningAssumptions:
    """Panel-to-billing conversion assumptions.

    Defaults are the practice's planning inputs from the NEH CoCM consolidated
    workbook (2026-09-20, Inputs sheet), every one of which that workbook
    labels "Illustrative / editable". They are NOT eligibility rules and never
    override the midpoint logic — they describe an expected panel, not a claim.
    """
    billable_conversion: float = 0.80   # billable months / active patients
    initial_month_share: float = 0.15   # share of billable months on 99492
    extra_units_per_month: float = 0.2  # average qualifying 99494 units / month
    caseload_per_fte: int = 60          # active patients per BHCM FTE (AIMS, complex/FQHC)
    fte_increment: float = 0.1          # budget rounding for BHCM FTE
    collection_realization: float = 0.94  # aggregate receipts / allowance
    private_factor_of_medicare_wi: float = 1.25  # commercial sensitivity, UNVERIFIED

    def __post_init__(self) -> None:
        for name in ("billable_conversion", "initial_month_share", "collection_realization"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {v}")
        if self.extra_units_per_month < 0 or self.private_factor_of_medicare_wi < 0:
            raise ValueError("extra_units_per_month and private_factor_of_medicare_wi must be >= 0")
        if self.caseload_per_fte <= 0 or self.fte_increment <= 0:
            raise ValueError("caseload_per_fte and fte_increment must be positive")


PLANNING_ASSUMPTIONS_SOURCE = (
    "NEH-CoCM-Spravato-FQHC-Consolidated-2026-09-20.xlsx (Inputs sheet) — "
    "labeled 'Illustrative / editable'; AIMS caseload guidance (2023)"
)
PRIVATE_MIX_KEY = "private"
DEFAULT_PAYER_MIX: dict[str, float] = {"wi-medicaid": 0.70, "medicare-wi": 0.10, PRIVATE_MIX_KEY: 0.20}


def blended_month_allowance(payer: str, a: PlanningAssumptions = PlanningAssumptions()) -> float | None:
    """Expected allowance per billable CoCM month under one payer.

    = initial_share × 99492 + (1 − initial_share) × 99493 + extra_units × 99494.
    None when any of the three CPT rates is unpriced for the payer.
    """
    r = {c: rate_info(c, payer).rate_usd for c in ("99492", "99493", "99494")}
    if any(v is None for v in r.values()):
        return None
    return round(
        a.initial_month_share * r["99492"] + (1 - a.initial_month_share) * r["99493"]
        + a.extra_units_per_month * r["99494"], 2,
    )


def plan_capacity(
    active_patients: float,
    payer_mix: Mapping[str, float] | None = None,
    assumptions: PlanningAssumptions = PlanningAssumptions(),
) -> dict[str, Any]:
    """Convert an active CoCM panel into expected billable months, staffing and allowance.

    payer_mix maps payer ids (and optionally 'private') to shares summing to 1.
    'private' is priced as medicare-wi × private_factor_of_medicare_wi and
    labeled estimated. Returns only billing-side quantities; labor, overhead
    and PPS economics live in the practice workbook, not here.
    """
    if active_patients < 0:
        raise ValueError("active_patients must be >= 0")
    mix = dict(payer_mix if payer_mix is not None else DEFAULT_PAYER_MIX)
    bad = [k for k in mix if k not in PAYERS and k != PRIVATE_MIX_KEY]
    if bad:
        raise ValueError(f"unknown payer_mix keys: {bad} (use {', '.join(PAYERS)}, {PRIVATE_MIX_KEY})")
    if any(v < 0 for v in mix.values()) or abs(sum(mix.values()) - 1.0) > 1e-6:
        raise ValueError("payer_mix shares must be >= 0 and sum to 1.0")

    a = assumptions
    billable_months = active_patients * a.billable_conversion
    fte_exact = active_patients / a.caseload_per_fte
    fte_budgeted = math.ceil(fte_exact / a.fte_increment - 1e-9) * a.fte_increment

    per_payer: list[dict[str, Any]] = []
    gross = 0.0
    priced_confidences: list[RateConfidence] = []
    all_priced = True
    for payer, share in mix.items():
        months = billable_months * share
        if payer == PRIVATE_MIX_KEY:
            base = blended_month_allowance("medicare-wi", a)
            allowance = None if base is None else round(base * a.private_factor_of_medicare_wi, 2)
            conf: RateConfidence = "estimated"
            src = f"medicare-wi × {a.private_factor_of_medicare_wi} (commercial sensitivity, UNVERIFIED)"
        else:
            allowance = blended_month_allowance(payer, a)
            conf = price_claim(["99492", "99493", "99494"], payer).confidence
            src = PAYER_MODELS[payer].source
        row = {
            "payer": payer, "share": share, "billable_months": round(months, 1),
            "allowance_per_billable_month_usd": allowance,
            "rate_confidence": conf or None, "rate_source": src,
        }
        if allowance is None:
            all_priced = False
            row["gross_allowance_usd"] = None
        else:
            row["gross_allowance_usd"] = round(months * allowance, 2)
            gross += months * allowance
            priced_confidences.append(conf)
        per_payer.append(row)
    # Weakest priced line governs, as in ClaimPricing.confidence.
    confidence: RateConfidence = (
        max(priced_confidences, key=lambda c: _CONFIDENCE_RANK[c]) if priced_confidences else ""
    )

    return {
        "active_patients": active_patients,
        "billable_months": round(billable_months, 1),
        "expected_units": {
            "99492": round(billable_months * a.initial_month_share, 1),
            "99493": round(billable_months * (1 - a.initial_month_share), 1),
            "99494": round(billable_months * a.extra_units_per_month, 1),
        },
        "bhcm_fte_required": round(fte_exact, 4),
        "bhcm_fte_budgeted": round(fte_budgeted, 1),
        "per_payer": per_payer,
        "gross_allowance_usd": round(gross, 2),
        "expected_collections_usd": round(gross * a.collection_realization, 2),
        "all_payers_priced": all_priced,
        "rate_confidence": confidence or None,
        "assumptions": {
            "billable_conversion": a.billable_conversion,
            "initial_month_share": a.initial_month_share,
            "extra_units_per_month": a.extra_units_per_month,
            "caseload_per_fte": a.caseload_per_fte,
            "fte_increment": a.fte_increment,
            "collection_realization": a.collection_realization,
            "private_factor_of_medicare_wi": a.private_factor_of_medicare_wi,
            "source": PLANNING_ASSUMPTIONS_SOURCE,
        },
        "note": (
            "Planning scenario, not a forecast: expected units are panel averages, "
            "eligibility per patient-month still follows the midpoint rule. WI Medicaid "
            "months under the 99493 minimum earn nothing (G2214 absent). CHCs receive "
            "PPS encounters, not these fees. Private allowance is a sensitivity."
        ),
    }


# ---------------------------------------------------------------------------
# Code catalogue display
# ---------------------------------------------------------------------------

_CATEGORY_ORDER = [
    "CoCM", "General BHI", "RHC/FQHC", "APCM add-on", "APCM base",
    "WI Medicaid BHIC", "Initiating",
]
_CATEGORY_LABELS = {
    "CoCM":        "CoCM — Collaborative Care Model",
    "General BHI": "General BHI — Non-CoCM Behavioral Health Integration",
    "RHC/FQHC":    "RHC / FQHC Setting",
    "APCM add-on": f"APCM Companion Add-ons (CY2026 — require {'/'.join(APCM_BASE_CODES)})",
    "APCM base":   "APCM Base Codes (prerequisite for the add-ons; rates not modeled)",
    "WI Medicaid BHIC": "WI Medicaid BHIC Contract (ForwardHealth portal — verified)",
    "Initiating":  "Valid Initiating Visit Codes (required before first CoCM/BHI month)",
}
_CONFIDENCE_MARK = {"portal_verified": "", "verified_primary": "", "verified_secondary": "†",
                    "estimated": "~", "": ""}


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
            if c.payers != PAYERS:
                details.append("Payers: " + ", ".join(c.payers) + ".")
            if c.notes:
                details.append(c.notes)
            for d in details:
                for ln in _wrap(d):
                    print(f"  {'':14}  ↳ {ln}")


def print_rate_table() -> None:
    print(f"\n{'─' * 72}")
    print("  Rate table (USD per unit — decision-support)")
    print(f"{'─' * 72}")
    print(f"  {'Code':<8}{'Medicare WI':>14}{'Medicare FQHC':>15}{'WI Medicaid':>14}  Status")
    for c in COCM_CODES + BHI_CODES + APCM_ADDON_CODES + FQHC_CODES + WI_MEDICAID_BHIC_CODES:
        cells = []
        for payer in PAYERS:
            info = rate_info(c.code, payer)
            if info.rate_usd is None:
                cells.append("—")
            else:
                cells.append(f"{info.rate_usd:,.2f}{_CONFIDENCE_MARK[info.confidence]}")
        status = "" if c.status == "active" else c.status.upper()
        print(f"  {c.code:<8}{cells[0]:>14}{cells[1]:>15}{cells[2]:>14}  {status}")
    print(
        "\n  unmarked  portal_verified / verified_primary (payer's published file, "
        "dated)\n"
        "  †  verified_secondary (computed from the January RVU26A release in the "
        "NEH\n     rate memo; re-verify against RVU26C)\n"
        "  ~  estimated — UNVERIFIED\n"
        "  —  not priced: not covered under the payer, discontinued, or not in the\n"
        "     verification set (load via RATE_OVERRIDES_JSON).\n"
    )
    for p in PAYERS:
        m = PAYER_MODELS[p]
        print(f"  {p}: {m.description}.")
        for ln in _wrap(f"{m.source}. {m.caveat}", 66):
            print(f"      {ln}")
    print("  HOLD/DISCONTINUED codes are flagged by price_claim() warnings.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_mix(text: str) -> dict[str, float]:
    mix: dict[str, float] = {}
    for part in text.split(","):
        k, _, v = part.strip().partition("=")
        if not k or not v:
            raise argparse.ArgumentTypeError("payer mix must look like wi-medicaid=0.7,medicare-wi=0.1,private=0.2")
        mix[k.strip()] = float(v)
    return mix


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
        "--apcm-enrolled", default="no",
        help="yes | no (default no): patient receives APCM (G0556–G0558) from the same "
             "practitioner this month — selects the G0568/G0569/G0570 add-on pathway",
    )
    ap.add_argument(
        "--payer", choices=PAYERS, default="medicare-wi",
        help="Rate model for estimated payment (default: medicare-wi)",
    )
    ap.add_argument("--capacity-plan", type=float, metavar="ACTIVE_PATIENTS",
                    help="Plan billable months, BHCM FTE and allowance for an active CoCM panel")
    ap.add_argument("--payer-mix", type=_parse_mix, metavar="MIX",
                    help="capacity plan payer shares, e.g. wi-medicaid=0.7,medicare-wi=0.1,private=0.2")
    ap.add_argument("--list-codes", action="store_true",
                    help="Print the full supported code catalogue + rate table and exit")
    args = ap.parse_args()

    if args.list_codes:
        print_code_catalogue()
        print_rate_table()
        print(f"\n{SOURCE_LINE}\nDisclaimer: {DISCLAIMER}")
        return 0

    if args.capacity_plan is not None:
        try:
            plan = plan_capacity(args.capacity_plan, args.payer_mix)
        except ValueError as exc:
            ap.error(str(exc))
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        print(f"\n{SOURCE_LINE}\nDisclaimer: {DISCLAIMER}")
        return 0

    if args.minutes is None:
        ap.error("--minutes is required")
    if args.initiating_visit is None:
        ap.error("--initiating-visit is required")

    _yes = ("yes", "y", "true", "1")
    iv = args.initiating_visit.strip().lower() in _yes
    apcm = args.apcm_enrolled.strip().lower() in _yes

    if args.mode == "bhi":
        result = evaluate_bhi(args.minutes, iv, apcm_enrolled=apcm)
    else:
        if not args.month:
            ap.error("--month (initial | subsequent) is required in cocm mode")
        result = evaluate_cocm(args.minutes, args.month, iv, apcm_enrolled=apcm)

    # Price the eligible codes under the selected payer model.
    if result.get("eligible_code"):
        pricing = price_claim(result["eligible_code"].split(" + "), args.payer)
        result["payer"] = args.payer
        if pricing.total_usd is not None:
            result["estimated_payment_usd"] = f"{pricing.total_usd:,.2f}"
            result["rate_confidence"] = pricing.confidence
            result["rate_source"] = pricing.sources
        if pricing.unpriced_codes:
            result["unpriced_codes"] = ", ".join(pricing.unpriced_codes)
            result["unpriced_reason"] = " | ".join(
                f"{ln.code}: {ln.note}" for ln in pricing.lines if ln.rate_usd is None
            )
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
