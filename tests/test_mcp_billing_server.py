"""Tests for the MCP tool layer (mcp/cocm_billing_server.py) — tool functions
are called directly (no transport), so this covers input validation, the JSON
contract each tool returns, rule warnings, error shapes, and the
mcp/evaluation.xml questions end-to-end through the tools.
"""
from __future__ import annotations

import asyncio
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mcp"))

import cocm_billing_server as srv  # noqa: E402

j = json.loads


def test_seven_tools_registered_with_read_only_annotations():
    tools = asyncio.run(srv.mcp.list_tools())
    names = sorted(t.name for t in tools)
    assert names == sorted([
        "billing_evaluate_cocm", "billing_evaluate_bhi", "billing_list_codes",
        "billing_get_rate", "billing_price_claim", "billing_evaluate_panel",
        "billing_plan_capacity",
    ])
    for t in tools:
        assert t.annotations is not None
        ann = t.annotations.model_dump(by_alias=True)  # SDK 1.x camelCase / 2.x snake_case
        assert ann.get("readOnlyHint", ann.get("read_only_hint")) is True, t.name


def test_every_response_carries_disclaimer_with_full_source_chain():
    r = j(srv.billing_get_rate(srv.GetRateInput(code="99492")))
    for src in ("MLN909432", "CMS-1832-F", "MM14315", "NACHC", "RVU26C", "ForwardHealth", "2026-09-20"):
        assert src in r["disclaimer"]
    assert r["payer_model"]["source"].startswith("CMS CY2026 RVU/GPCI")


def test_evaluate_cocm_contract_and_apcm_path():
    r = j(srv.billing_evaluate_cocm(srv.CocmInput(minutes=116, month="subsequent", initiating_visit=True)))
    assert r["eligible_code"] == "99493 + 99494 + 99494"
    assert r["estimated_payment_usd"] == round(138.71 + 2 * 58.72, 2)
    assert r["rate_confidence"] == "verified_primary" and "RVU26C" in r["rate_source"]
    assert r["threshold_confidence"].startswith("verified_primary")
    assert "warnings" not in r

    a = j(srv.billing_evaluate_cocm(srv.CocmInput(
        minutes=116, month="subsequent", initiating_visit=True, apcm_enrolled=True)))
    assert a["eligible_code"] == "G0569" and a["cpt_alternative"] == "99493 + 99494 + 99494"
    assert a["estimated_payment_usd"] == 139.45
    assert any("billing hold" in w for w in a["warnings"])
    assert any("G0556/G0557/G0558" in w for w in a["warnings"])


def test_evaluate_bhi_apcm_path_and_medicaid_not_covered():
    r = j(srv.billing_evaluate_bhi(srv.BhiInput(minutes=24, initiating_visit=True, apcm_enrolled=True, payer="wi-medicaid")))
    assert r["eligible_code"] == "G0570" and r["unpriced_codes"] == ["G0570"]
    assert "estimated_payment_usd" not in r and "not covered" in r["unpriced_reason"]["G0570"]
    g = j(srv.billing_evaluate_cocm(srv.CocmInput(minutes=30, month="subsequent", initiating_visit=True, payer="wi-medicaid")))
    assert g["eligible_code"] == "G2214" and "unbilled" in g["unpriced_reason"]["G2214"]


def test_price_claim_warns_on_mirror_pair_but_still_totals():
    r = j(srv.billing_price_claim(srv.PriceClaimInput(codes=["99492", "G0568"])))
    assert r["total_usd"] == round(153.19 + 154.25, 2)
    assert any("duplicate-service" in w for w in r["warnings"])
    assert {ln["code"]: ln["status"] for ln in r["lines"]} == {"99492": "active", "G0568": "hold"}


def test_unknown_code_returns_actionable_error():
    r = j(srv.billing_get_rate(srv.GetRateInput(code="99999")))
    assert "error" in r and "99492" in r["valid_codes"] and "billing_list_codes" in r["suggestion"]
    r = j(srv.billing_price_claim(srv.PriceClaimInput(codes=["99493", "XXXX1"])))
    assert "error" in r


def test_discontinued_code_is_labeled_in_rate_lookup():
    r = j(srv.billing_get_rate(srv.GetRateInput(code="G0512")))
    assert r["status"] == "discontinued" and r["rate_usd"] is None and "2026-01-01" in r["note"]


def test_input_validation_rejects_bad_payloads():
    with pytest.raises(ValidationError):
        srv.CocmInput(minutes=-1, month="initial", initiating_visit=True)
    with pytest.raises(ValidationError):
        srv.CocmInput(minutes=30, month="third", initiating_visit=True)
    with pytest.raises(ValidationError):
        srv.PriceClaimInput(codes=[])
    with pytest.raises(ValidationError):
        srv.GetRateInput(code="99492", payer="aetna")


def test_panel_buckets_and_per_patient_warnings():
    r = j(srv.billing_evaluate_panel(srv.PanelInput(patients=[
        srv.PanelPatient(patient_id="PT-001", mode="cocm", minutes=72, month="initial"),
        srv.PanelPatient(patient_id="PT-002", mode="cocm", minutes=45, month="initial", initiating_visit=False),
        srv.PanelPatient(patient_id="PT-003", mode="bhi", minutes=19),
        srv.PanelPatient(patient_id="PT-004", mode="cocm", minutes=70, month="initial", apcm_enrolled=True),
        srv.PanelPatient(patient_id="PT-005", mode="cocm", minutes=40),  # month missing
    ])))
    assert (r["billable"], r["blocked_no_initiating_visit"], r["under_threshold"]) == (2, 1, 1)
    per = {p["patient_id"]: p for p in r["per_patient"]}
    assert per["PT-002"]["action"].startswith("document a qualifying initiating visit")
    assert per["PT-004"]["eligible_code"] == "G0568" and per["PT-004"]["warnings"]
    assert "error" in per["PT-005"]
    assert r["code_tally"] == {"99492": 1, "G0568": 1}
    assert r["total_estimated_revenue_usd"] == round(153.19 + 154.25, 2)


def test_list_codes_exposes_per_payer_rates_with_provenance():
    codes = {c["code"]: c for c in j(srv.billing_list_codes(srv.ListCodesInput(category="CoCM")))["codes"]}
    assert codes["99492"]["rates"]["wi-medicaid"]["rate_usd"] == 146.05
    assert codes["99492"]["rates"]["wi-medicaid"]["rate_confidence"] == "verified_primary"
    assert "20260905" in codes["99492"]["rates"]["wi-medicaid"]["rate_source"]
    assert codes["G2214"]["payers"] == ["medicare-wi", "medicare-fqhc"]
    assert "wi-medicaid" not in codes["G2214"]["rates"]


def test_capacity_plan_tool_contract_and_errors():
    r = j(srv.billing_plan_capacity(srv.CapacityPlanInput(active_patients=125)))
    assert r["billable_months"] == 100.0 and r["bhcm_fte_budgeted"] == 2.1
    assert {p["payer"] for p in r["per_payer"]} == {"wi-medicaid", "medicare-wi", "private"}
    assert r["rate_confidence"] == "estimated" and "Illustrative" in r["assumptions"]["source"]
    m = j(srv.billing_plan_capacity(srv.CapacityPlanInput(active_patients=60, payer_mix={"medicare-fqhc": 1.0})))
    assert m["rate_confidence"] == "verified_primary" and m["all_payers_priced"] is True
    e = j(srv.billing_plan_capacity(srv.CapacityPlanInput(active_patients=60, payer_mix={"wi-medicaid": 0.4})))
    assert "error" in e and "private" in e["valid_mix_keys"]
    with pytest.raises(ValidationError):
        srv.CapacityPlanInput(active_patients=10, payer_mix={"medicare-natl": 1.0})


def test_evaluation_xml_answers_through_the_tools():
    answers = [qa.find("answer").text.strip()
               for qa in ET.parse(REPO / "mcp" / "evaluation.xml").getroot().findall("qa_pair")]
    got = [
        str(j(srv.billing_evaluate_cocm(srv.CocmInput(minutes=137, month="subsequent", initiating_visit=True)))["addon_30min_units"]),
        str(j(srv.billing_evaluate_cocm(srv.CocmInput(minutes=36, month="initial", initiating_visit=True, payer="medicare-wi")))["estimated_payment_usd"]),
        str(j(srv.billing_price_claim(srv.PriceClaimInput(codes=["99492", "99494", "99494", "99494"], payer="medicare-fqhc")))["total_usd"]),
        str(j(srv.billing_get_rate(srv.GetRateInput(code="99493", payer="wi-medicaid")))["rate_usd"]),
        str(j(srv.billing_get_rate(srv.GetRateInput(code="S0280", payer="wi-medicaid")))["rate_usd"]),
        str(j(srv.billing_list_codes(srv.ListCodesInput(category="Initiating")))["count"]),
        str(j(srv.billing_evaluate_cocm(srv.CocmInput(minutes=85, month="initial", initiating_visit=True)))["next_99494_at_min"]),
        str(j(srv.billing_evaluate_panel(srv.PanelInput(patients=[
            srv.PanelPatient(patient_id="PT-A", mode="cocm", minutes=70, month="initial"),
            srv.PanelPatient(patient_id="PT-B", mode="cocm", minutes=29, month="subsequent"),
            srv.PanelPatient(patient_id="PT-C", mode="bhi", minutes=20)])))["billable"]),
        str(round(j(srv.billing_get_rate(srv.GetRateInput(code="99492")))["rate_usd"]
                  - j(srv.billing_get_rate(srv.GetRateInput(code="99493")))["rate_usd"], 2)),
        next(c["code"] for c in j(srv.billing_list_codes(srv.ListCodesInput(category="APCM add-on")))["codes"]
             if c["mirror_of"] == "99493"),
        str(j(srv.billing_plan_capacity(srv.CapacityPlanInput(active_patients=125)))["bhcm_fte_budgeted"]),
        str(next(p for p in j(srv.billing_plan_capacity(srv.CapacityPlanInput(
            active_patients=100, payer_mix={"wi-medicaid": 1.0})))["per_payer"])["allowance_per_billable_month_usd"]),
    ]
    assert got == answers
