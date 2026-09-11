#!/usr/bin/env python3
"""medsync8_billing_mcp — MCP server for CoCM/BHI billing decision support.

Exposes the MedSync8 billing tracker (scripts/cocm_time_tracker.py) as MCP
tools: midpoint-rule eligibility, the full code catalogue, per-payer rate
lookups, claim pricing, and whole-panel evaluation.

All tools are read-only and deterministic. Every response carries the
standing disclaimer: decision-support only — verify against the current CMS
Physician Fee Schedule and the ForwardHealth portal before claim submission.

Run (stdio):
    python3 mcp/cocm_billing_server.py

Register in Claude Code via .mcp.json (see repo root) or:
    claude mcp add medsync8-billing -- python3 mcp/cocm_billing_server.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

try:
    from mcp.server.fastmcp import FastMCP  # mcp 1.x
except ModuleNotFoundError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
from pydantic import BaseModel, ConfigDict, Field

# Import the tracker as the single source of billing truth.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cocm_time_tracker import (  # noqa: E402
    ALL_CODES,
    CODE_MAP,
    DISCLAIMER as TRACKER_DISCLAIMER,
    PAYERS,
    SOURCE_LINE,
    THRESHOLD_CONFIDENCE,
    evaluate_bhi,
    evaluate_cocm,
    price_claim,
    rate_info,
)

# Single provenance string, derived from the tracker's SOURCES.
DISCLAIMER = f"{TRACKER_DISCLAIMER} {SOURCE_LINE}."

Payer = Literal["medicare-natl", "medicare-wi", "wi-medicaid"]

mcp = FastMCP("medsync8_billing_mcp")


def _json(payload: dict[str, Any]) -> str:
    payload["disclaimer"] = DISCLAIMER
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _attach_pricing(result: dict[str, Any], payer: str) -> dict[str, Any]:
    if result.get("eligible_code"):
        pricing = price_claim(result["eligible_code"].split(" + "), payer)
        result["payer"] = payer
        if pricing.total_usd is not None:
            result["estimated_payment_usd"] = pricing.total_usd
            result["rate_confidence"] = pricing.confidence  # weakest line
            result["rate_source"] = pricing.sources
        if pricing.unpriced_codes:
            result["unpriced_codes"] = pricing.unpriced_codes
        if pricing.warnings:
            result["warnings"] = pricing.warnings
    result["threshold_confidence"] = THRESHOLD_CONFIDENCE
    return result


def _line(info: Any) -> dict[str, Any]:
    return {
        "code": info.code,
        "rate_usd": info.rate_usd,
        "rate_confidence": info.confidence or None,
        "status": info.status,
        "rate_source": info.source or None,
        "note": info.note,
    }


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class CocmInput(BaseModel):
    """Input for a single-patient CoCM month evaluation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    minutes: int = Field(
        ..., ge=0, le=1440,
        description="Accrued BH care-manager clinical minutes this calendar month (e.g., 72)",
    )
    month: Literal["initial", "subsequent"] = Field(
        ..., description="'initial' = first CoCM month (99492 path); 'subsequent' = later months (99493 path)",
    )
    initiating_visit: bool = Field(
        ..., description="True if a qualifying initiating visit is on file (99202-99215, G0402, G0438/G0439, 99495/99496, 90791/90792)",
    )
    payer: Payer = Field(
        default="medicare-natl",
        description="Rate model for the payment estimate",
    )


class BhiInput(BaseModel):
    """Input for a single-patient General BHI (99484) month evaluation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    minutes: int = Field(..., ge=0, le=1440, description="Accrued BHI clinical-staff minutes this calendar month")
    initiating_visit: bool = Field(..., description="True if a qualifying initiating visit is on file")
    payer: Payer = Field(default="medicare-natl", description="Rate model for the payment estimate")


class ListCodesInput(BaseModel):
    """Input for listing the billing code catalogue."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    category: (
        Literal["CoCM", "General BHI", "RHC/FQHC", "APCM add-on", "WI Medicaid BHIC", "Initiating"] | None
    ) = Field(default=None, description="Filter to one category; omit for the full catalogue")


class GetRateInput(BaseModel):
    """Input for a single code/payer rate lookup."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(..., min_length=4, max_length=12, description="CPT/HCPCS code, e.g. '99492', 'G2214', 'H0038'")
    payer: Payer = Field(default="medicare-natl", description="Rate model")


class PriceClaimInput(BaseModel):
    """Input for pricing a list of billed codes."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    codes: list[str] = Field(
        ..., min_length=1, max_length=50,
        description="Codes as billed, repeats allowed for multi-unit add-ons, e.g. ['99493', '99494', '99494']",
    )
    payer: Payer = Field(default="medicare-natl", description="Rate model")


class PanelPatient(BaseModel):
    """One patient-month in a panel evaluation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    patient_id: str = Field(..., min_length=1, max_length=40, description="Synthetic identifier only — never PHI (e.g., 'PT-001')")
    mode: Literal["cocm", "bhi"] = Field(default="cocm", description="Billing track for this patient")
    minutes: int = Field(..., ge=0, le=1440, description="Accrued minutes this calendar month")
    month: Literal["initial", "subsequent"] | None = Field(
        default=None, description="Required when mode='cocm'; ignored for bhi",
    )
    initiating_visit: bool = Field(default=True, description="Qualifying initiating visit on file")


class PanelInput(BaseModel):
    """Input for evaluating a whole panel for one calendar month."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    patients: list[PanelPatient] = Field(..., min_length=1, max_length=500, description="Patient-months to evaluate")
    payer: Payer = Field(default="medicare-natl", description="Rate model for revenue totals")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="billing_evaluate_cocm",
    annotations={
        "title": "Evaluate CoCM Month Eligibility",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def billing_evaluate_cocm(params: CocmInput) -> str:
    """Determine which CoCM code(s) a patient-month supports under the CMS midpoint rule.

    Applies 99492 (initial, >=36 min), 99493 (subsequent, >=31 min), 99494
    add-on units (first at target+16, then every 30 min), and G2214 (>=30 min
    when the base minimum is unmet). Returns the eligible code combination,
    add-on unit count, the minute threshold for the next 99494 unit, the APCM
    add-on alternative (apcm_alternative — only for APCM-enrolled patients;
    either/or with the CPT code, currently on billing hold), a payment
    estimate under the selected payer model, and any rule warnings. RHC/FQHC
    settings bill these same codes (G0512 was discontinued 2026-01-01).

    Returns:
        str: JSON with eligible_code, addon_30min_units, next_99494_at_min,
             apcm_alternative, estimated_payment_usd, rate_confidence,
             rate_source, warnings, note, threshold_confidence, disclaimer.
    """
    result = evaluate_cocm(params.minutes, params.month, params.initiating_visit)
    return _json(_attach_pricing(result, params.payer))


@mcp.tool(
    name="billing_evaluate_bhi",
    annotations={
        "title": "Evaluate General BHI Month Eligibility",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def billing_evaluate_bhi(params: BhiInput) -> str:
    """Determine 99484 (General BHI) eligibility for a patient-month.

    Requires >=20 clinical-staff minutes and a qualifying initiating visit.
    Flags the same-month exclusivity with 99492/99493 and the G0570 APCM
    alternative. Includes a payment estimate under the selected payer model.

    Returns:
        str: JSON with eligible_code, estimated_payment_usd, rate_confidence,
             note, disclaimer.
    """
    result = evaluate_bhi(params.minutes, params.initiating_visit)
    return _json(_attach_pricing(result, params.payer))


@mcp.tool(
    name="billing_list_codes",
    annotations={
        "title": "List Billing Code Catalogue",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def billing_list_codes(params: ListCodesInput) -> str:
    """List the supported CoCM/BHI billing code catalogue, optionally by category.

    Categories: 'CoCM' (99492/99493/99494/G2214), 'General BHI' (99484),
    'RHC/FQHC' (G0512 — DISCONTINUED 2026-01-01, historical only), 'APCM
    add-on' (G0568/G0569/G0570 — status 'hold', Medicare-only, either/or with
    their mirror CPT code), 'WI Medicaid BHIC' (H0038/S0280/S0281 —
    portal-verified ForwardHealth rates), 'Initiating' (valid initiating-visit
    codes). Each entry carries its status, rule fields (mirror_of,
    requires_any_of, exclusive_with, payers) and rate provenance.

    Returns:
        str: JSON list of codes with description, category, minute thresholds,
             status/status_note, rule fields, rates, rate_confidence,
             rate_source, and notes.
    """
    codes = [c for c in ALL_CODES if params.category is None or c.category == params.category]
    return _json({
        "count": len(codes),
        "codes": [
            {
                "code": c.code,
                "description": c.description,
                "category": c.category,
                "status": c.status,
                "status_note": c.status_note or None,
                "target_min": c.target_min,
                "min_to_bill": c.min_to_bill,
                "medicare_natl_usd": c.medicare_natl,
                "wi_medicaid_usd": c.wi_medicaid,
                "rate_confidence": c.rate_confidence or None,
                "rate_source": c.rate_source or None,
                "mirror_of": c.mirror_of,
                "requires_any_of": list(c.requires_any_of) or None,
                "exclusive_with": list(c.exclusive_with) or None,
                "payers": list(c.payers),
                "notes": c.notes or None,
            }
            for c in codes
        ],
    })


@mcp.tool(
    name="billing_get_rate",
    annotations={
        "title": "Get Code Rate for a Payer",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def billing_get_rate(params: GetRateInput) -> str:
    """Look up the modeled rate for one CPT/HCPCS code under a payer model.

    Payers: 'medicare-natl' (CY2026 national non-facility), 'medicare-wi'
    (NGS J6 statewide locality, GPCI-adjusted estimate), 'wi-medicaid'
    (ForwardHealth portal values where loaded, otherwise a labeled estimate).

    Returns:
        str: JSON with code, payer, rate_usd (null when discontinued, not
             covered under the payer, or not modeled — see note), rate_confidence,
             status (active|hold|discontinued), rate_source, and note. If the
             code is unknown, lists valid codes.
    """
    code = params.code.upper() if params.code[0].isalpha() else params.code
    if code not in CODE_MAP:
        return _json({
            "error": f"Unknown code '{params.code}'.",
            "valid_codes": sorted(CODE_MAP.keys()),
            "suggestion": "Use billing_list_codes to browse the catalogue.",
        })
    info = rate_info(code, params.payer)
    return _json({"payer": params.payer, **_line(info)})


@mcp.tool(
    name="billing_price_claim",
    annotations={
        "title": "Price a Claim Line Set",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def billing_price_claim(params: PriceClaimInput) -> str:
    """Total the modeled payment for a list of billed codes under one payer.

    Repeat a code for multiple units (e.g., ['99493', '99494', '99494'] for a
    subsequent month with two add-on blocks). Codes without a modeled rate are
    returned in unpriced_codes rather than silently dropped. Catalogue rules
    are enforced: warnings are returned for codes on billing hold or
    discontinued, missing prerequisites (e.g. 99494 without a base code, an
    APCM add-on without G0556–G0558), and same-month exclusivity violations
    (e.g. 99492 + G0568, 99492 + G2214, 99484 + 99493). A claim with warnings
    is still totaled so the exposure is visible, but must not be submitted.

    Returns:
        str: JSON with per-code lines (rate, confidence, status, source, note),
             total_usd, unpriced_codes, warnings, disclaimer.
    """
    unknown = [c for c in params.codes if c not in CODE_MAP]
    if unknown:
        return _json({
            "error": f"Unknown code(s): {unknown}",
            "valid_codes": sorted(CODE_MAP.keys()),
            "suggestion": "Use billing_list_codes to browse the catalogue.",
        })
    pricing = price_claim(params.codes, params.payer)
    return _json({
        "payer": params.payer,
        "lines": [_line(i) for i in pricing.lines],
        "total_usd": pricing.total_usd,
        "unpriced_codes": pricing.unpriced_codes or None,
        "warnings": pricing.warnings or None,
    })


@mcp.tool(
    name="billing_evaluate_panel",
    annotations={
        "title": "Evaluate a Whole Panel Month",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def billing_evaluate_panel(params: PanelInput) -> str:
    """Evaluate an entire patient panel for one calendar month and total revenue.

    Runs each patient-month through the appropriate eligibility path (CoCM or
    General BHI), tallies billed code units, sums estimated revenue under the
    selected payer, and separates non-billable patients into actionable
    buckets (blocked on initiating visit vs. under minute threshold).
    Use synthetic patient identifiers only — never PHI.

    Returns:
        str: JSON with per-patient results, code_tally, billable/blocked/
             under_threshold counts, total_estimated_revenue_usd, disclaimer.
    """
    per_patient, tally = [], {}
    billable = blocked = under = 0
    revenue = 0.0
    for p in params.patients:
        if p.mode == "cocm":
            if p.month is None:
                per_patient.append({"patient_id": p.patient_id, "error": "month required for cocm mode"})
                continue
            r = evaluate_cocm(p.minutes, p.month, p.initiating_visit)
        else:
            r = evaluate_bhi(p.minutes, p.initiating_visit)
        code = r.get("eligible_code")
        entry = {"patient_id": p.patient_id, "eligible_code": code, "minutes": p.minutes}
        if code:
            billable += 1
            codes = code.split(" + ")
            for c in codes:
                tally[c] = tally.get(c, 0) + 1
            pricing = price_claim(codes, params.payer)
            if pricing.total_usd is not None:
                entry["estimated_payment_usd"] = pricing.total_usd
                revenue += pricing.total_usd
            if pricing.warnings:
                entry["warnings"] = pricing.warnings
        elif not p.initiating_visit:
            blocked += 1
            entry["action"] = "document a qualifying initiating visit"
        else:
            under += 1
            entry["action"] = "under minute threshold this month"
        per_patient.append(entry)
    return _json({
        "payer": params.payer,
        "patients_evaluated": len(params.patients),
        "billable": billable,
        "blocked_no_initiating_visit": blocked,
        "under_threshold": under,
        "code_tally": dict(sorted(tally.items())),
        "total_estimated_revenue_usd": round(revenue, 2),
        "per_patient": per_patient,
    })


if __name__ == "__main__":
    mcp.run()
