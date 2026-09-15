"""Billing-logic tests for scripts/cocm_time_tracker.py — the single source of
billing truth. Covers the CMS boundary edges required by AGENTS.md /
tests.instructions.md, the catalogue rule engine, payer coverage, provenance
labels, and keeps mcp/evaluation.xml derived from the code rather than
hand-transcribed.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from cocm_time_tracker import (  # noqa: E402
    APCM_BASE_CODES,
    APCM_MIRROR,
    CODE_MAP,
    PAYERS,
    WI_GPCI_FACTOR,
    WI_MEDICAID_FACTOR,
    claim_warnings,
    evaluate_bhi,
    evaluate_cocm,
    price_claim,
    price_codes,
    rate_info,
)


# ---------------------------------------------------------------------------
# CMS midpoint-rule boundaries (MLN909432)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("minutes,month,expected", [
    (29, "initial", None), (30, "initial", "G2214"),
    (35, "initial", "G2214"), (36, "initial", "99492"),
    (85, "initial", "99492"), (86, "initial", "99492 + 99494"),
    (115, "initial", "99492 + 99494"), (116, "initial", "99492 + 99494 + 99494"),
    (29, "subsequent", None), (30, "subsequent", "G2214"),
    (31, "subsequent", "99493"),
    (75, "subsequent", "99493"), (76, "subsequent", "99493 + 99494"),
    (105, "subsequent", "99493 + 99494"), (106, "subsequent", "99493 + 99494 + 99494"),
])
def test_cocm_boundaries(minutes, month, expected):
    assert evaluate_cocm(minutes, month, True)["eligible_code"] == expected


def test_next_99494_threshold_formula():
    r = evaluate_cocm(116, "subsequent", True)
    assert r["addon_30min_units"] == 2
    assert r["next_99494_at_min"] == 60 + 16 + 2 * 30
    assert evaluate_cocm(136, "subsequent", True)["addon_30min_units"] == 3


@pytest.mark.parametrize("minutes,expected", [(19, None), (20, "99484")])
def test_bhi_boundary(minutes, expected):
    assert evaluate_bhi(minutes, True)["eligible_code"] == expected


def test_initiating_visit_gate_blocks_both_tracks():
    assert evaluate_cocm(120, "initial", False)["eligible_code"] is None
    assert evaluate_bhi(45, False)["eligible_code"] is None


def test_apcm_alternative_derived_from_catalogue():
    assert APCM_MIRROR == {"99492": "G0568", "99493": "G0569", "99484": "G0570"}
    alt = evaluate_cocm(72, "initial", True)["apcm_alternative"]
    assert alt.startswith("G0568") and "never both" in alt and "billing hold" in alt
    assert evaluate_bhi(24, True)["apcm_alternative"].startswith("G0570")
    assert "G0512" not in evaluate_cocm(72, "initial", True)["note"]


def test_apcm_enrolled_path_selects_g_code_with_cpt_alternative():
    r = evaluate_cocm(116, "subsequent", True, apcm_enrolled=True)
    assert r["eligible_code"] == "G0569" and r["cpt_alternative"] == "99493 + 99494 + 99494"
    assert r["mode"].endswith("(APCM pathway)") and "not time-based" in r["note"].lower()
    assert "apcm_alternative" not in r and "next_99494_at_min" not in r
    p = price_claim([r["eligible_code"]], "medicare-natl")
    assert p.total_usd == 145.96 and any("billing hold" in w for w in p.warnings)
    b = evaluate_bhi(24, True, apcm_enrolled=True)
    assert b["eligible_code"] == "G0570" and b["cpt_alternative"] == "99484"


@pytest.mark.parametrize("minutes,month,expected", [(35, "initial", "G2214"), (29, "initial", None)])
def test_apcm_enrolled_is_conservatively_gated_below_threshold(minutes, month, expected):
    r = evaluate_cocm(minutes, month, True, apcm_enrolled=True)
    assert r["eligible_code"] == expected and "not recommended this month" in r["note"]
    assert evaluate_bhi(19, True, apcm_enrolled=True)["eligible_code"] is None


def test_apcm_flag_never_changes_no_initiating_visit_result():
    assert evaluate_cocm(120, "initial", False, apcm_enrolled=True)["eligible_code"] is None


@pytest.mark.parametrize("minutes,month,expected", [
    (36, "initial", "G0568"), (35, "initial", "G2214"),
    (31, "subsequent", "G0569"), (30, "subsequent", "G2214"),
])
def test_apcm_unlock_boundaries(minutes, month, expected):
    assert evaluate_cocm(minutes, month, True, apcm_enrolled=True)["eligible_code"] == expected


def test_apcm_bhi_unlock_boundary_and_wording():
    assert evaluate_bhi(20, True, apcm_enrolled=True)["eligible_code"] == "G0570"
    note = evaluate_bhi(20, True, apcm_enrolled=True)["note"]
    assert "99494" not in note and "practice policy" in note  # BHI-shaped, honestly labeled


def test_default_path_snapshot_unaffected_by_apcm_feature():
    r = evaluate_cocm(116, "subsequent", True)
    assert set(r) == {"mode", "accrued_minutes", "month", "eligible_code", "base_min_met",
                      "addon_30min_units", "next_99494_at_min", "apcm_alternative", "note"}
    assert r["mode"] == "CoCM" and "cpt_alternative" not in r


def test_well_formed_apcm_claim_only_warns_about_the_hold():
    w = claim_warnings(["G0568", "G0556"])
    assert len(w) == 1 and "billing hold" in w[0]
    assert rate_info("G0556", "medicare-natl").note == "not modeled"
    assert rate_info("G0557", "wi-medicaid").note == "not covered under wi-medicaid"


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

def test_mirror_pair_is_flagged_as_duplicate_service():
    w = claim_warnings(["99492", "G0568"])
    assert any("duplicate-service" in x for x in w)
    assert any("billing hold" in x for x in w)
    assert any("/".join(APCM_BASE_CODES) in x for x in w)


@pytest.mark.parametrize("pair", [("99492", "G2214"), ("99493", "G2214"),
                                  ("99484", "99492"), ("99484", "99493"),
                                  ("99492", "99493")])
def test_same_month_exclusivity(pair):
    w = claim_warnings(list(pair))
    assert len([x for x in w if "never both" in x]) == 1


def test_addon_requires_base_code():
    assert any("requires one of 99492/99493" in x for x in claim_warnings(["99494"]))
    assert claim_warnings(["99493", "99494", "99494"]) == []


def test_clean_claim_has_no_warnings_and_totals():
    p = price_claim(["99493", "99494", "99494"], "medicare-natl")
    assert p.warnings == [] and p.total_usd == round(144.96 + 2 * 61.46, 2)
    assert price_codes(["99493", "99494", "99494"], "medicare-natl")[0] == p.total_usd


def test_claim_confidence_is_weakest_line():
    # 99492 (verified_secondary) + a wi-medicaid estimate line → estimated overall
    assert price_claim(["99492"], "medicare-natl").confidence == "verified_secondary"
    assert price_claim(["99492", "99494"], "medicare-wi").confidence == "estimated"
    assert price_claim(["G0512"], "medicare-natl").confidence == ""


def test_discontinued_is_distinguishable_from_unknown():
    d = rate_info("G0512", "medicare-natl")
    u = rate_info("ZZZZ", "medicare-natl")
    assert d.status == "discontinued" and "2026-01-01" in d.note and d.rate_usd is None
    assert u.status == "unknown"
    assert any("discontinued" in x for x in claim_warnings(["G0512"]))


# ---------------------------------------------------------------------------
# Payer coverage and provenance
# ---------------------------------------------------------------------------

def test_medicare_only_codes_never_get_medicaid_estimates():
    for g in ("G0568", "G0569", "G0570"):
        info = rate_info(g, "wi-medicaid")
        assert info.rate_usd is None and "not covered" in info.note
        assert rate_info(g, "medicare-natl").status == "hold"


def test_bhic_codes_are_medicaid_only_and_portal_verified():
    assert rate_info("S0280", "wi-medicaid").confidence == "portal_verified"
    assert rate_info("S0280", "wi-medicaid").rate_usd == 473.64
    assert rate_info("S0280", "medicare-natl").rate_usd is None


def test_every_rate_has_a_source_and_no_label_upgrade_without_one():
    for c in CODE_MAP.values():
        if c.medicare_natl is not None:
            assert c.rate_confidence in ("verified_secondary", "estimated"), c.code
            assert c.rate_source, f"{c.code} has a rate but no rate_source"
    # 99484 is crosswalk-derived, not independently published → must stay estimated.
    assert CODE_MAP["99484"].rate_confidence == "estimated"


def test_estimates_are_labeled_estimated_for_every_payer():
    assert rate_info("99492", "medicare-wi").confidence == "estimated"
    assert rate_info("99492", "wi-medicaid").confidence == "estimated"
    assert rate_info("99492", "medicare-wi").rate_usd == round(160.32 * WI_GPCI_FACTOR, 2)


def test_unknown_payer_rejected():
    with pytest.raises(ValueError):
        rate_info("99492", "aetna")
    assert set(PAYERS) == {"medicare-natl", "medicare-wi", "wi-medicaid"}


# ---------------------------------------------------------------------------
# mcp/evaluation.xml stays derived from the code
# ---------------------------------------------------------------------------

def _eval_answers() -> list[str]:
    tree = ET.parse(REPO / "mcp" / "evaluation.xml")
    return [qa.find("answer").text.strip() for qa in tree.getroot().findall("qa_pair")]


def test_evaluation_fixture_matches_code():
    natl = lambda c: rate_info(c, "medicare-natl").rate_usd  # noqa: E731
    expected = [
        str(evaluate_cocm(137, "subsequent", True)["addon_30min_units"]),
        str(rate_info("99492", "medicare-wi").rate_usd),
        str(price_claim(["99492", "99494", "99494", "99494"], "medicare-natl").total_usd),
        str(round(natl("G2214") * WI_MEDICAID_FACTOR, 2)),
        str(rate_info("S0280", "wi-medicaid").rate_usd),
        str(sum(1 for c in CODE_MAP.values() if c.category == "Initiating")),
        str(evaluate_cocm(85, "initial", True)["next_99494_at_min"]),
        "2",  # PT-A 70 initial + PT-B 29 subsequent + PT-C 20 bhi → two billable
        str(round(natl("99492") - natl("99493"), 2)),
        APCM_MIRROR["99493"],
    ]
    assert _eval_answers() == expected
