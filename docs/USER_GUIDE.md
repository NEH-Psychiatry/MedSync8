# MedSync8 — User Guide

**Psychiatry AI Workbench** · clinical AI tools for psychiatric practice, powered by Claude.

This guide covers everyday use of the web app, the command-line clinical utilities, and the operational basics. For developer/architecture details see `CLAUDE.md`; for deployment runbooks see `RUNBOOK.md`.

---

## 1. Quick Start

```bash
npm install
cp .env.example .env      # add your ANTHROPIC_API_KEY
npm run dev               # frontend on :5173, API proxy on :3001
```

Open **http://localhost:5173**. The only required configuration is `ANTHROPIC_API_KEY` in `.env` — the Express server refuses to start without it.

---

## 2. The Web App

### 2.1 The five tools

Pick a tool from the toolbar; each one loads a specialized system prompt on the server (your key and prompts never reach the browser):

| Tool | Icon | What it produces |
|---|---|---|
| **Policy** | 📋 | Legally defensible clinical policies — PURPOSE / SCOPE / PROCEDURES structure with DEA, state-board, and PDMP citations |
| **Supervision** | 🩺 | NP/PA supervision checklists, competency rubrics, feedback forms with rating scales |
| **Lecture** | 🎓 | CME-style educational content — learning objectives, case vignettes, clinical pearls, references |
| **Consult** | 💬 | Clinical consultation on telepsychiatry, controlled-substance prescribing, collaborative practice, licensure |
| **Documents** | 📄 | SOAP notes, prior-auth letters, psych evals, discharge summaries — areas needing your customization are flagged in [BRACKETS] |

Each tool keeps its **own conversation history** — switching tools doesn't lose your thread.

### 2.2 Ways to prompt

- **Type freely** in the message box; responses stream in token-by-token.
- **Quick Prompts** — one-click starter prompts tailored to the active tool.
- **Template Library** (Templates panel) — 10 pre-built templates across all five tools, e.g. *Telepsychiatry CS Policy Shell*, *Monthly Supervision Log*, *Adult ADHD Lecture (60 min)*, *DEA Telehealth FAQ*, *ADHD SOAP Note*, *Prior Auth Letter — Stimulants*. Clicking a template drops the full prompt into the right tool and sends it.

### 2.3 Saving and exporting

On any assistant response you can:

- **Save** — stored in your browser's localStorage; survives refreshes and restarts. No server round-trip, nothing leaves your machine.
- **Copy** — copies the full response to the clipboard.
- **Export PDF** — renders the response to a printable PDF.

Panels in the header:

- **Dashboard** — usage stats and your five most recent saved responses.
- **Saved** — the full saved-response archive, filterable by tool.
- **Templates** — the template library (opening it safely cancels any in-flight streaming response).

### 2.4 Error handling

Messages beginning with ⚠️ are error notices (rate limit, network, upstream API), not clinical content. The proxy rate-limits at **20 requests/minute** per client; wait a moment and retry.

---

## 3. Command-Line Clinical Utilities (`scripts/`)

### 3.1 CoCM / BHI billing tracker — `cocm_time_tracker.py`

Decision-support for Collaborative Care Model and General BHI billing under the CMS midpoint rule.

```bash
# CoCM — initial month, 72 min accrued
python3 scripts/cocm_time_tracker.py --minutes 72 --month initial --initiating-visit yes

# CoCM — subsequent month with an add-on unit
python3 scripts/cocm_time_tracker.py --minutes 116 --month subsequent --initiating-visit yes

# General BHI (99484 path)
python3 scripts/cocm_time_tracker.py --mode bhi --minutes 25 --initiating-visit yes

# Full code catalogue (CoCM, BHI, initiating-visit codes)
python3 scripts/cocm_time_tracker.py --list-codes
python3 scripts/cocm_time_tracker.py --capacity-plan 125 --payer-mix wi-medicaid=0.7,medicare-wi=0.1,private=0.2
```

What it applies:

| Code | Rule |
|---|---|
| **99492** | Initial month — billable ≥ 36 min (target 70) |
| **99493** | Subsequent month — billable ≥ 31 min (target 60) |
| **99494** | Add-on per 30-min block — first unit at target + 16, next every 30 min, no cap |
| **G2214** | ≥ 30 min but base minimum unmet |
| **99484** | General BHI — ≥ 20 min; never in the same month as 99492/99493 |

The output includes `next_99494_at_min` — the minute count at which your next add-on unit unlocks — an `estimated_payment_usd` under the chosen `--payer` (`medicare-wi` — Medicare PFS Wisconsin locality; `medicare-fqhc` — CMS designated RHC/FQHC rates; `wi-medicaid` — ForwardHealth fee-for-service max fees) with its `rate_confidence` and `rate_source` (the CMS or ForwardHealth file the amount came from, as recorded in the practice's rate-verification workbook), an `unpriced_reason` whenever a payer has no verified amount for a code (G2214 is absent from every ForwardHealth schedule, so a sub-threshold month earns nothing from WI Medicaid), and `warnings` whenever a claim breaks a catalogue rule: same-month exclusivity (99484 vs 99492/99493, G2214 vs a base code), a 99494 without its base code, or anything involving the CY2026 APCM add-ons **G0568/G0569/G0570** — which require an APCM base code, are *either/or* with their mirror CPT code, and are on **billing hold** pending written MAC confirmation. **G0512 was discontinued 2026-01-01**; RHC/FQHC settings bill the standard codes. A warned claim is still totaled so you can see the exposure, but must not be submitted. For a patient who receives APCM from the same practitioner, add `--apcm-enrolled yes`: the result becomes the G-code add-on (with the CPT set shown as `cpt_alternative`), gated on the CPT minimum as practice policy (CMS itself sets no minute requirement for the add-ons) and still carrying the hold warning. The standing disclaimer applies: verify against the current CMS Physician Fee Schedule and the ForwardHealth portal (sources: CMS MLN909432, CMS-1832-F, MM14315, NACHC APCM Tip Sheet, AIMS Center).

`--capacity-plan N` turns an active CoCM panel into expected billable months, 99492/99493/99494 units, behavioral health care manager FTE (exact and budget-rounded), and allowance per payer in the mix. The defaults (80% billable conversion, 15% initial-month share, 0.2 extra units, 60 patients per FTE, 94% collection realization, private at 125% of Medicare WI) are the practice's planning inputs and are labeled illustrative in the output; `private` is always an estimate. It is a planning scenario, not a forecast, and never changes what a given patient-month can bill.

An initiating visit (office E/M 99202–99215, AWV, Welcome to Medicare, TCM 99495/99496, or psychiatric eval 90791/90792) is required before the first CoCM/BHI month; run with `--initiating-visit no` to see the blocking message and valid visit list.

### 3.2 Credentialing risk alert — `credentialing_alert.py`

Reads the licensing/credentialing star-schema workbook, classifies every credential by urgency, and posts a ranked **Microsoft Teams** card. Intended to run daily at 08:00 (America/Chicago) from a scheduler.

```bash
export CREDENTIALING_WORKBOOK=/path/to/star-schema.xlsx
export TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
# optional second channel:
export TEAMS_CHANNEL_WEBHOOK=https://outlook.office.com/webhook/...
python3 scripts/credentialing_alert.py
```

Urgency bands:

| Band | Meaning | Action line in the card |
|---|---|---|
| 🛑 LAPSED | Expiry date has passed | STOP-WORK — do not schedule; verify scope |
| 🔴 CRITICAL | ≤ 30 days | Submit renewal this week; notify supervisor |
| 🟠 URGENT | ≤ 60 days | Open renewal file now |
| 🟡 WATCH | ≤ 90 days | Schedule the application |
| ⚪ STALLED | No expiry; application open > 60 days | Follow up with issuing authority |
| ⚪ PENDING | No expiry; recent application | Monitor issuance |
| OK | > 90 days out | (not shown in the card) |

The card also flags **data-integrity mismatches** (a computed-expiring credential whose DimStatus still says "Active"). Exit codes: `0` success, `1` Teams delivery failed, `2` workbook missing/unreadable — wire these into your scheduler's alerting. No PHI is transmitted — aggregate risk metadata only.

### 3.3 Billing-auditor agent

For Claude Code users: the repo ships a custom subagent at `.claude/agents/billing-auditor.md`. It automatically audits any change touching billing thresholds against CMS MLN909432 — deriving expected results independently, running the tracker at boundary minutes (e.g. 35 vs 36, target+15 vs +16), and reporting PASS/FAIL findings with rule citations. Invoke it directly with *"have billing-auditor check the tracker."* It is read-only — it reports, never edits.

---

## 4. Backends at a Glance

The repo is a dual-app layout: the root workbench (`src/` + `server.js`) and the RAG telepsychiatry assistant (`frontend/` + `backend/`). The `frontend/` client renders RAG citations and deploys to Cloudflare Pages (`VITE_API_BASE` points it at the FastAPI backend); run it with `cd frontend && npm install && npm run dev`, test with `npm test`.

| | Express proxy (`server.js`) | FastAPI (`backend/server.py`) |
|---|---|---|
| Use for | Local dev, simple deployments | Production (Azure Container Apps / Fly.io) |
| Model | `claude-opus-4-8`, adaptive thinking | `claude-opus-4-8` (override via `ANTHROPIC_MODEL`) |
| Extras | Rate limiting, sanitization, SSE streaming | Everything at left **plus** RAG over `corpus/`, Cloudflare Access JWT auth, hash-only audit log |

**RAG:** drop reference documents into `corpus/` and the FastAPI backend retrieves relevant chunks into the system prompt, returning citations with each reply. The index rebuilds automatically and caches to `corpus/index.json`.

**Audit:** every chat is logged append-only as a salted SHA-256 hash of the query (never raw text) with user identity, tool, latency, and citation count — HIPAA-ready by design. Set `AUDIT_SALT` in production. Review recent events at `GET /api/audit/recent`.

**Auth:** set `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` to require Cloudflare Access JWTs. **Without them all endpoints are public — dev only.**

---

## 5. Deployment (Summary)

- **Azure Container Apps** — push to `main` triggers `.github/workflows/deploy-azure.yml`: image builds to GHCR, Bicep (`azure/main.bicep`) deploys a Container App with an Azure Files `/data` volume, Log Analytics, and 0→3 replica autoscale. One-time setup (resource group, service principal, GitHub secrets) is documented step-by-step in `CLAUDE.md` → *Azure Deployment*.
- **Fly.io** — `fly.toml` is included for the lighter path.
- **HIPAA note:** execute a BAA with your cloud provider at the subscription level *before* storing any PHI.

---

## 6. Troubleshooting

| Symptom | Likely cause · fix |
|---|---|
| Server exits immediately at startup | `ANTHROPIC_API_KEY` missing from `.env` |
| ⚠️ "Rate limited" in chat | 20 req/min proxy cap or Anthropic-side 429 — wait and retry |
| ⚠️ "Invalid API key" | Key is wrong/expired — check `.env`, restart `npm run dev` |
| Responses stop mid-stream when switching panels | Expected — opening Templates cancels the in-flight stream |
| FastAPI: replies have no citations | Empty `corpus/`, embedder unavailable, or `use_rag: false` |
| Credentialing alert exits 2 | Workbook path wrong or sheet/table names don't match the star schema |
| Credentialing alert exits 1 | Teams webhook unreachable or `TEAMS_WEBHOOK_URL` unset |
| Saved responses disappeared | localStorage is per-browser/per-device; clearing site data erases them |

---

*Decision-support disclaimers apply throughout: billing outputs must be verified against the current CMS Physician Fee Schedule, and all generated clinical content requires clinician review before use.*
