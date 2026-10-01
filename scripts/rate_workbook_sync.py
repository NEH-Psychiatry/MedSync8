#!/usr/bin/env python3
"""rate_workbook_sync.py — connect the billing tracker to the practice's Excel rate workbook.

Reads the NEH rate-verification workbook (``NEH-CoCM-Spravato-FQHC-Consolidated-
<date>.xlsx``) and turns its **Rates** sheet into tracker overrides and its
**Inputs** sheet into capacity-planning assumptions, so the workbook — not a
hand transcription — is the thing the model runs on.

What it does
------------
* ``--check``            reconcile the workbook against the tracker's catalogue
                         rates; exit 1 on any mismatch (CI-friendly).
* ``--write-overrides``  write a ``RATE_OVERRIDES_JSON``-shaped file; point the
                         tracker at it with ``RATE_OVERRIDES_FILE=<path>``.
* ``--write-assumptions`` write the planning assumptions the workbook carries.

Workbook contract (Rates sheet): a header row containing ``Rate / input``,
``Value``, ``Unit``, ``Evidence status``, ``Source / locator``, ``Use
limitation``. Rows are matched to a payer by label prefix and to a code by the
CPT/HCPCS token at the end of the label::

    Medicare WI office 99492   -> medicare-wi   / 99492
    Medicare WI G2214          -> medicare-wi   / G2214
    Medicare FQHC 99493        -> medicare-fqhc / 99493
    Wisconsin FFS 99494        -> wi-medicaid   / 99494

Evidence status maps to a tracker confidence label: an official payer file
(``snapshot``, ``designated rate``, ``Recomputed from … file``) is
``verified_primary``; anything else that is not ``Illustrative`` is
``verified_secondary``; ``Illustrative / editable`` rows are never rates.

Only codes in the tracker catalogue are emitted by default (``--all`` keeps the
rest, e.g. Spravato G2082/G2083, for other consumers). Decision-support only.

Usage
-----
    python3 scripts/rate_workbook_sync.py --workbook path/to/workbook.xlsx --check
    python3 scripts/rate_workbook_sync.py --workbook wb.xlsx --write-overrides rates.json \
        --write-assumptions assumptions.json
    RATE_OVERRIDES_FILE=rates.json python3 scripts/cocm_time_tracker.py --list-codes
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cocm_time_tracker import (  # noqa: E402
    CODE_MAP,
    PAYERS,
    PlanningAssumptions,
    rate_info,
)

RATES_SHEET = "Rates"
INPUTS_SHEET = "Inputs"
RATES_HEADER = ("Rate / input", "Value", "Unit", "Evidence status", "Source / locator", "Use limitation")
INPUTS_HEADER = ("Assumption", "Value", "Unit", "Evidence status", "Basis / limitation")

# Label prefix -> tracker payer. Order matters: longer prefixes first.
PAYER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("medicare wi office", "medicare-wi"),
    ("medicare fqhc", "medicare-fqhc"),
    ("medicare wi", "medicare-wi"),
    ("wisconsin ffs", "wi-medicaid"),
)
_CODE_RE = re.compile(r"\b([0-9]{5}|[A-Z][0-9]{4})\b")

# Inputs-sheet assumption label -> PlanningAssumptions field.
ASSUMPTION_LABELS: dict[str, str] = {
    "cocm billable conversion": "billable_conversion",
    "cocm initial-month share": "initial_month_share",
    "cocm extra units / billable month": "extra_units_per_month",
    "active caseload / bhcm fte": "caseload_per_fte",
    "bhcm budget increment": "fte_increment",
    "collection realization": "collection_realization",
}


@dataclass(frozen=True)
class WorkbookRate:
    payer: str
    code: str
    usd: float
    confidence: str
    source: str
    note: str
    label: str
    in_catalogue: bool


@dataclass(frozen=True)
class ReconcileRow:
    payer: str
    code: str
    workbook_usd: float
    tracker_usd: float | None
    tracker_confidence: str
    status: str   # match | mismatch | not_in_tracker | not_in_catalogue


def _norm(v: Any) -> str:
    return " ".join(str(v).split()).strip() if v is not None else ""


def _find_header(rows: Iterable[tuple[Any, ...]], header: tuple[str, ...]) -> tuple[int, dict[str, int]] | None:
    first = header[0].lower()
    for i, row in enumerate(rows):
        cells = [_norm(c).lower() for c in row]
        if first in cells:
            cols = {h: cells.index(h.lower()) for h in header if h.lower() in cells}
            if len(cols) >= 3:
                return i, cols
    return None


def confidence_for(evidence: str) -> str | None:
    """Map a workbook evidence-status cell to a tracker confidence label (None = not a rate)."""
    e = evidence.lower()
    if not e or "illustrative" in e:
        return None
    if any(k in e for k in ("snapshot", "designated rate", "recomputed from", "fee file", "cms 2026 gaf")):
        return "verified_primary"
    return "verified_secondary"


def classify_label(label: str) -> tuple[str, str] | None:
    """Return (payer, code) for a Rates-sheet label, or None if it is not a payer rate row."""
    low = label.lower()
    for prefix, payer in PAYER_PREFIXES:
        if low.startswith(prefix):
            m = _CODE_RE.search(label[len(prefix):])
            if m:
                return payer, m.group(1)
    return None


def _sheet_rows(path: Path, name: str) -> list[tuple[Any, ...]]:
    import openpyxl  # local import keeps the tracker itself dependency-free

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if name not in wb.sheetnames:
        raise ValueError(f"workbook has no {name!r} sheet (found {wb.sheetnames})")
    return [tuple(r) for r in wb[name].iter_rows(values_only=True)]


def load_workbook_rates(path: Path, include_all: bool = False) -> list[WorkbookRate]:
    """Parse the Rates sheet into per-payer rates with provenance."""
    rows = _sheet_rows(path, RATES_SHEET)
    found = _find_header(rows, RATES_HEADER)
    if found is None:
        raise ValueError(f"{RATES_SHEET} sheet: header row {RATES_HEADER[:2]} not found")
    start, cols = found
    out: list[WorkbookRate] = []
    for row in rows[start + 1:]:
        label = _norm(row[cols["Rate / input"]] if cols["Rate / input"] < len(row) else None)
        parsed = classify_label(label) if label else None
        if parsed is None:
            continue
        payer, code = parsed
        raw = row[cols["Value"]] if cols["Value"] < len(row) else None
        try:
            usd = round(float(str(raw).replace("$", "").replace(",", "")), 2)
        except (TypeError, ValueError):
            continue
        conf = confidence_for(_norm(row[cols["Evidence status"]]) if "Evidence status" in cols else "")
        if conf is None:
            continue
        src = _norm(row[cols["Source / locator"]]) if "Source / locator" in cols else ""
        note = _norm(row[cols["Use limitation"]]) if "Use limitation" in cols else ""
        in_cat = code in CODE_MAP
        if in_cat or include_all:
            out.append(WorkbookRate(payer, code, usd, conf,
                                    f"{src} — read from {path.name} (Rates sheet)" if src else f"{path.name} (Rates sheet)",
                                    note, label, in_cat))
    return out


def load_planning_assumptions(path: Path) -> PlanningAssumptions:
    """Parse the Inputs sheet into PlanningAssumptions (missing rows keep the tracker default)."""
    rows = _sheet_rows(path, INPUTS_SHEET)
    found = _find_header(rows, INPUTS_HEADER)
    if found is None:
        raise ValueError(f"{INPUTS_SHEET} sheet: header row {INPUTS_HEADER[:2]} not found")
    start, cols = found
    values: dict[str, float] = {}
    for row in rows[start + 1:]:
        label = _norm(row[cols["Assumption"]] if cols["Assumption"] < len(row) else None).lower()
        field_name = ASSUMPTION_LABELS.get(label)
        if field_name is None:
            continue
        raw = row[cols["Value"]] if cols["Value"] < len(row) else None
        try:
            text = str(raw).replace("$", "").replace(",", "").strip()
            v = float(text.rstrip("%")) / (100.0 if text.endswith("%") else 1.0)
        except (TypeError, ValueError):
            continue
        values[field_name] = int(v) if field_name == "caseload_per_fte" else v
    return PlanningAssumptions(**values)


def to_overrides(rates: Iterable[WorkbookRate]) -> dict[str, dict[str, dict[str, Any]]]:
    """Shape rates as the RATE_OVERRIDES_JSON document the tracker consumes."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rates:
        if r.payer in PAYERS and r.in_catalogue:
            out.setdefault(r.payer, {})[r.code] = {
                "usd": r.usd, "confidence": r.confidence, "source": r.source, "note": r.note,
            }
    return out


def reconcile(rates: Iterable[WorkbookRate]) -> list[ReconcileRow]:
    """Compare workbook rates with the tracker's catalogue (overrides excluded)."""
    rows: list[ReconcileRow] = []
    for r in rates:
        if not r.in_catalogue:
            rows.append(ReconcileRow(r.payer, r.code, r.usd, None, "", "not_in_catalogue"))
            continue
        base = CODE_MAP[r.code].rates.get(r.payer)
        if base is None or r.payer not in CODE_MAP[r.code].payers:
            rows.append(ReconcileRow(r.payer, r.code, r.usd, None, "", "not_in_tracker"))
            continue
        status = "match" if abs(base.usd - r.usd) < 0.005 else "mismatch"
        rows.append(ReconcileRow(r.payer, r.code, r.usd, base.usd, base.confidence, status))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workbook", required=True, type=Path, help="path to the .xlsx rate-verification workbook")
    ap.add_argument("--check", action="store_true", help="reconcile against the tracker; exit 1 on mismatch")
    ap.add_argument("--all", action="store_true", help="keep codes outside the tracker catalogue too")
    ap.add_argument("--write-overrides", type=Path, metavar="JSON", help="write RATE_OVERRIDES_JSON-shaped file")
    ap.add_argument("--write-assumptions", type=Path, metavar="JSON", help="write PlanningAssumptions as JSON")
    args = ap.parse_args(argv)

    try:
        rates = load_workbook_rates(args.workbook, include_all=args.all)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not rates:
        print("error: no payer rate rows recognised in the Rates sheet", file=sys.stderr)
        return 2

    print(f"{args.workbook.name}: {len(rates)} rate rows read")
    rows = reconcile(rates)
    width = max(len(r.code) for r in rows)
    for r in rows:
        tracker = "—" if r.tracker_usd is None else f"{r.tracker_usd:,.2f} ({r.tracker_confidence})"
        print(f"  {r.payer:<14} {r.code:<{width}}  workbook {r.workbook_usd:>9,.2f}  tracker {tracker:<30} {r.status}")
    mismatches = [r for r in rows if r.status == "mismatch"]
    rc = 0
    if args.check and mismatches:
        print(f"CHECK FAILED: {len(mismatches)} mismatch(es) — update the tracker catalogue from the workbook", file=sys.stderr)
        rc = 1
    elif args.check:
        print("CHECK OK: every workbook rate matches the tracker catalogue")

    if args.write_overrides:
        args.write_overrides.write_text(json.dumps(to_overrides(rates), indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {args.write_overrides} — use RATE_OVERRIDES_FILE={args.write_overrides}")
    if args.write_assumptions:
        try:
            a = load_planning_assumptions(args.workbook)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        payload = {**asdict(a), "source": f"{args.workbook.name} (Inputs sheet) — labeled Illustrative / editable"}
        args.write_assumptions.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {args.write_assumptions}")
    # Surface a sample so the operator can see the connection is live.
    sample = rate_info("99492", "wi-medicaid")
    print(f"tracker now prices 99492 under wi-medicaid at {sample.rate_usd} ({sample.confidence})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
