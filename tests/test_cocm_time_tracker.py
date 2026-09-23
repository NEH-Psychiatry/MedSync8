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
    RATE_CONFIDENCE_LEVELS,
    PlanningAssumptions,
    _parse_overrides,
    blended_month_allowance,
    claim_warnings,
    evaluate_bhi,
    evaluate_cocm,
    plan_capacity,
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
    p = price_claim([r["eligible_code"]], "medicare-wi")
    assert p.total_usd == 139.45 and any("billing hold" in w for w in p.warnings)
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
    assert "Rate not modeled" in rate_info("G0556", "medicare-wi").note
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
    p = price_claim(["99493", "99494", "99494"], "medicare-wi")
    assert p.warnings == [] and p.total_usd == round(138.71 + 2 * 58.72, 2)
    assert price_codes(["99493", "99494", "99494"], "medicare-wi")[0] == p.total_usd
    assert price_claim(["99493", "99494", "99494"], "medicare-fqhc").total_usd == round(144.96 + 2 * 61.46, 2)
    assert price_claim(["99493", "99494", "99494"], "wi-medicaid").total_usd == round(141.61 + 2 * 60.51, 2)


def test_claim_confidence_is_weakest_line():
    # 99493 (verified_primary, RVU26C) + G0569 (verified_secondary, RVU26A memo) → secondary overall
    assert price_claim(["99492"], "medicare-wi").confidence == "verified_primary"
    assert price_claim(["99493", "G0569"], "medicare-wi").confidence == "verified_secondary"
    assert price_claim(["G0512"], "medicare-wi").confidence == ""


def test_discontinued_is_distinguishable_from_unknown():
    d = rate_info("G0512", "medicare-wi")
    u = rate_info("ZZZZ", "medicare-wi")
    assert d.status == "discontinued" and "2026-01-01" in d.note and d.rate_usd is None
    assert u.status == "unknown"
    assert any("discontinued" in x for x in claim_warnings(["G0512"]))


# ---------------------------------------------------------------------------
# Payer coverage and provenance (real numbers — NEH workbook 2026-09-20)
# ---------------------------------------------------------------------------

WORKBOOK_RATES = {  # Rates sheet, NEH-CoCM-Spravato-FQHC-Consolidated-2026-09-20.xlsx
    "medicare-wi":   {"99492": 153.19, "99493": 138.71, "99494": 58.72},
    "medicare-fqhc": {"99492": 160.32, "99493": 144.96, "99494": 61.46},
    "wi-medicaid":   {"99492": 146.05, "99493": 141.61, "99494": 60.51},
}


@pytest.mark.parametrize("payer", sorted(WORKBOOK_RATES))
def test_cpt_cocm_rates_match_the_verification_workbook(payer):
    for code, usd in WORKBOOK_RATES[payer].items():
        info = rate_info(code, payer)
        assert info.rate_usd == usd, (code, payer)
        assert info.confidence == "verified_primary"
        assert "2026" in info.source and ("computed in" in info.source or "read in" in info.source)


def test_wi_locality_memo_codes_are_secondary_until_reverified():
    for code, usd in {"G2214": 58.01, "99484": 55.04, "G0568": 154.25,
                      "G0569": 139.45, "G0570": 55.36}.items():
        info = rate_info(code, "medicare-wi")
        assert info.rate_usd == usd and info.confidence == "verified_secondary", code
        assert "RVU26A" in info.source and "re-verify" in info.source


def test_g2214_is_medicare_only_because_forwardhealth_omits_it():
    info = rate_info("G2214", "wi-medicaid")
    assert info.rate_usd is None and "not covered" in info.note and "unbilled" in info.note
    assert "wi-medicaid" not in CODE_MAP["G2214"].payers
    # A 30-min subsequent month earns nothing from WI Medicaid — and says so.
    p = price_claim([evaluate_cocm(30, "subsequent", True)["eligible_code"]], "wi-medicaid")
    assert p.total_usd is None and p.unpriced_codes == ["G2214"]


def test_unverified_slots_are_unpriced_not_estimated():
    for code, payer in (("99484", "wi-medicaid"), ("G2214", "medicare-fqhc"),
                        ("99484", "medicare-fqhc"), ("G0568", "medicare-fqhc")):
        info = rate_info(code, payer)
        assert info.rate_usd is None and info.confidence == "" and "RATE_OVERRIDES_JSON" in info.note, (code, payer)


def test_medicare_only_codes_never_get_medicaid_rates():
    for g in ("G0568", "G0569", "G0570"):
        info = rate_info(g, "wi-medicaid")
        assert info.rate_usd is None and "not covered" in info.note
        assert rate_info(g, "medicare-wi").status == "hold"


def test_bhic_codes_are_medicaid_only_and_portal_verified():
    assert rate_info("S0280", "wi-medicaid").confidence == "portal_verified"
    assert rate_info("S0280", "wi-medicaid").rate_usd == 473.64
    assert rate_info("S0280", "medicare-wi").rate_usd is None


def test_every_rate_has_a_source_and_nothing_in_the_catalogue_is_estimated():
    seen = 0
    for c in CODE_MAP.values():
        for payer, r in c.rates.items():
            seen += 1
            assert payer in c.payers, f"{c.code}: rate for a payer the code excludes"
            assert r.confidence in RATE_CONFIDENCE_LEVELS and r.confidence != "estimated", c.code
            assert r.source, f"{c.code}/{payer} has a rate but no source"
    assert seen == 17  # 3 CPT × 3 payers + G2214 + 99484 + 3 APCM add-ons + 3 BHIC


def test_overrides_add_or_replace_with_provenance(monkeypatch, capsys):
    env = {
        "RATE_OVERRIDES_JSON": '{"wi-medicaid": {"99484": {"usd": 41.28, "confidence": '
                               '"verified_primary", "source": "ForwardHealth query 2026-09-21"}, '
                               '"99492": 150.00}, "aetna": {"99492": 1}, '
                               '"medicare-wi": {"99492": {"usd": 1, "confidence": "made_up"}}}',
        "WI_MEDICAID_RATES_JSON": '{"S0281": 14.00}',
    }
    ov = _parse_overrides(env)
    assert ov["wi-medicaid"]["99484"].usd == 41.28
    assert ov["wi-medicaid"]["99484"].confidence == "verified_primary"
    assert ov["wi-medicaid"]["99492"].confidence == "portal_verified"  # bare-number shorthand
    assert ov["wi-medicaid"]["S0281"].usd == 14.00                       # legacy variable
    assert "99492" not in ov["medicare-wi"]                              # bad confidence rejected
    err = capsys.readouterr().err
    assert "unknown payer 'aetna'" in err and "made_up" not in err and "confidence must be" in err
    assert _parse_overrides({"RATE_OVERRIDES_JSON": "not json"}) == {p: {} for p in PAYERS}


def test_retired_and_unknown_payers_are_rejected_with_guidance():
    with pytest.raises(ValueError, match="medicare-fqhc"):
        rate_info("99492", "medicare-natl")
    with pytest.raises(ValueError, match="unknown payer"):
        rate_info("99492", "aetna")
    assert set(PAYERS) == {"medicare-wi", "medicare-fqhc", "wi-medicaid"}


# ---------------------------------------------------------------------------
# Capacity planning (workbook CoCM sheet reproduced from the rate tables)
# ---------------------------------------------------------------------------

def test_blended_allowance_reproduces_workbook_cocm_rows():
    # C01 Medicare FQHC $159.56 · C07 office Medicare $152.63 · C07 Medicaid $154.38
    assert blended_month_allowance("medicare-fqhc") == 159.56
    assert blended_month_allowance("medicare-wi") == 152.63
    assert blended_month_allowance("wi-medicaid") == 154.38


def test_plan_capacity_matches_workbook_base_case():
    plan = plan_capacity(125)  # default mix 70/10/20 Medicaid/Medicare/private
    assert plan["billable_months"] == 100.0 and plan["bhcm_fte_budgeted"] == 2.1
    assert plan["bhcm_fte_required"] == round(125 / 60, 4)
    assert plan["expected_units"] == {"99492": 15.0, "99493": 85.0, "99494": 20.0}
    rows = {r["payer"]: r for r in plan["per_payer"]}
    assert rows["wi-medicaid"]["billable_months"] == 70.0
    assert rows["private"]["rate_confidence"] == "estimated" and plan["rate_confidence"] == "estimated"
    assert plan["expected_collections_usd"] == round(plan["gross_allowance_usd"] * 0.94, 2)
    all_medicaid = plan_capacity(100, {"wi-medicaid": 1.0}, PlanningAssumptions(billable_conversion=1.0))
    assert abs(all_medicaid["gross_allowance_usd"] - 15437.80) < 0.5  # workbook C07
    assert all_medicaid["rate_confidence"] == "verified_primary"


def test_plan_capacity_validates_inputs():
    with pytest.raises(ValueError, match="sum to 1.0"):
        plan_capacity(10, {"wi-medicaid": 0.5})
    with pytest.raises(ValueError, match="unknown payer_mix"):
        plan_capacity(10, {"medicare-natl": 1.0})
    with pytest.raises(ValueError):
        PlanningAssumptions(billable_conversion=1.5)
    assert plan_capacity(0)["gross_allowance_usd"] == 0.0


# ---------------------------------------------------------------------------
# mcp/evaluation.xml stays derived from the code
# ---------------------------------------------------------------------------

def _eval_answers() -> list[str]:
    tree = ET.parse(REPO / "mcp" / "evaluation.xml")
    return [qa.find("answer").text.strip() for qa in tree.getroot().findall("qa_pair")]


def test_evaluation_fixture_matches_code():
    wi = lambda c: rate_info(c, "medicare-wi").rate_usd  # noqa: E731
    expected = [
        str(evaluate_cocm(137, "subsequent", True)["addon_30min_units"]),
        str(rate_info("99492", "medicare-wi").rate_usd),
        str(price_claim(["99492", "99494", "99494", "99494"], "medicare-fqhc").total_usd),
        str(rate_info("99493", "wi-medicaid").rate_usd),
        str(rate_info("S0280", "wi-medicaid").rate_usd),
        str(sum(1 for c in CODE_MAP.values() if c.category == "Initiating")),
        str(evaluate_cocm(85, "initial", True)["next_99494_at_min"]),
        "2",  # PT-A 70 initial + PT-B 29 subsequent + PT-C 20 bhi → two billable
        str(round(wi("99492") - wi("99493"), 2)),
        APCM_MIRROR["99493"],
        str(plan_capacity(125)["bhcm_fte_budgeted"]),
        str(blended_month_allowance("wi-medicaid")),
    ]
    assert _eval_answers() == expected
