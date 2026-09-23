# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

### Frontend (React + Vite 8 + Express proxy)
```bash
npm install              # install dependencies
npm run dev              # start both Vite (5173) and Express (3001) concurrently
npm run dev:client       # Vite dev server only
npm run dev:server       # Express proxy only
npm run build            # production build to dist/
```

### RAG frontend (`frontend/` — Vite 7 + React 19, separate package.json)
```bash
cd frontend && npm ci      # own dependency tree
npm run dev                # Vite dev server; set VITE_API_BASE to the FastAPI URL
npm test                   # vitest (jsdom) — src/__tests__/App.test.jsx
npm run lint && npm run build
```

### Python Backend (FastAPI + RAG)
```bash
pip install -r backend/requirements-test.txt   # test deps (no torch, fast install)
pip install -r backend/requirements.txt         # full deps (includes sentence-transformers)
python -m pytest backend/tests -q              # run backend tests
python -m pytest tests -q                      # run root tests (sync calculator)
python -m pytest backend/tests/test_server.py -v  # run a single test file
python -m pytest backend/tests/test_audit.py::test_hash_query_deterministic_and_salted  # single test
uvicorn backend.server:app --port 8000         # run FastAPI locally
```

### Clinical Scripts & MCP Server
```bash
python3 scripts/cocm_time_tracker.py --list-codes            # billing code catalogue + rate table
python3 scripts/cocm_time_tracker.py --minutes 72 --month initial --initiating-visit yes --payer medicare-wi
python3 scripts/credentialing_alert.py                       # needs CREDENTIALING_WORKBOOK + TEAMS_WEBHOOK_URL
pip install -r mcp/requirements.txt && python3 mcp/cocm_billing_server.py   # MCP server (stdio)
```

### CI
CI runs three jobs on every PR and push to main: `pytest backend/tests tests -q` (Python 3.11), the root workbench build, and `frontend/` lint + vitest + build (Node 20). The root suite includes `tests/test_cocm_time_tracker.py` (CMS boundaries, rule engine, provenance, and `mcp/evaluation.xml` derived from code) and `tests/test_plugin_sync.py`, which fails if the plugin's vendored tracker or MCP server drifts from the canonical copies. All workflow actions are pinned to full-length commit SHAs; Dependabot bumps them weekly (`.github/dependabot.yml`).

## Architecture

This is a **dual-app repository** — two independent React clients, two backends, sharing the same five tool system prompts. Both backends call `claude-opus-4-8` with adaptive thinking (`thinking: {type: "adaptive"}`); text-block filtering silently drops thinking blocks.

**Workbench (root `src/` + `server.js`, port 3001)** — the Express-proxied Psychiatry AI Workbench. `server.js` proxies to the Anthropic API with rate limiting (20 req/min), message sanitization (50KB cap), server-side API key, and SSE streaming. Exposes `POST /api/claude`, `POST /api/claude/stream`, `GET /api/health`. Vite proxies `/api` to it during development. Not deployed by any workflow.

**RAG telepsychiatry assistant (`frontend/` + `backend/server.py`, port 8080)** — the production path. `frontend/` is a separate Vite/React app (own `package.json`, vitest suite, `Citations.jsx`) that calls the FastAPI backend at `VITE_API_BASE` and deploys to Cloudflare Pages (`deploy-pages.yml`). The backend adds RAG retrieval over `corpus/`, Cloudflare Access JWT auth, and hash-only audit logging, and is deployed via Azure Container Apps or Fly.io. It exposes `POST /api/chat` (non-streaming; returns `reply` + `citations`), `GET /api/health`, `GET /api/audit/recent` — it does **not** implement `/api/claude/stream`. The Dockerfile prefetches the bge-small-en-v1.5 embedding model (~130MB). `RUNBOOK.md` documents the PHI boundary — no PHI until BAA + local embeddings are confirmed.

Do not remove either app as a "duplicate": the root workbench cannot render citations and the `frontend/` client cannot stream — they serve different backends.

### Frontend → Backend data flow
1. `src/api.js` calls `/api/claude/stream` via SSE
2. `server.js` validates the tool ID against `SYSTEM_PROMPTS`, sanitizes messages, streams via `anthropic.messages.stream()`
3. `src/App.jsx` appends chunks to the conversation via `setConversations` functional updaters (avoids stale closures during streaming)

### RAG pipeline (Python backend only)
`backend/retriever.py` indexes `corpus/` files → chunks with overlap → embeddings (local sentence-transformers or OpenAI) → cosine similarity search. Index cached to `corpus/index.json` keyed by embedder name. `backend/embedders.py` provides pluggable `Embedder` protocol (set `EMBED_BACKEND=local|openai`).

### Auth & Audit (Python backend only)
`backend/auth.py`: Optional Cloudflare Access JWT verification (enabled when `CF_ACCESS_TEAM_DOMAIN` + `CF_ACCESS_AUD` are set). `backend/audit.py`: Append-only JSONL log recording salted hashed queries (never raw text), user identity, tool, latency, and citation count. Never log raw query text or weaken the salting.

### Clinical billing stack
`scripts/cocm_time_tracker.py` is the **single source of billing truth**: CMS midpoint-rule eligibility (99492 ≥36, 99493 ≥31, 99494 at target+16 then every 30, G2214 ≥30, 99484 ≥20), the code catalogue, and a three-payer rate model (`medicare-wi` = Medicare PFS Wisconsin locality computed from the CMS CY2026 RVU26C release; `medicare-fqhc` = CMS designated RHC/FQHC care-coordination rates; `wi-medicaid` = ForwardHealth fee-for-service max fees, 2026-09-05 snapshot). **Rates are data, not factors**: every (code, payer) amount is an explicit `Rate(usd, confidence, source, note)` in `BillingCode.rates`, transcribed from the practice's verification workbook (`NEH-CoCM-Spravato-FQHC-Consolidated-2026-09-20.xlsx`, Rates sheet) and the WI rate-card memo; nothing is derived from a GPCI or Medicaid factor any more, and a slot with no verified amount is *unpriced*, never estimated (`RATE_OVERRIDES_JSON` per payer, or the legacy `WI_MEDICAID_RATES_JSON`, adds one with its own label and source). `medicare-natl` is retired (`RETIRED_PAYERS` explains why: its figures were the FQHC rates). `PAYER_MODELS` carries each payer's source and caveat (WI: a psychiatrist cannot be the CoCM billing practitioner; CHCs use the T1015 PPS pathway). G2214 is Medicare-only (absent from every ForwardHealth schedule). **Billing rules are data, not prose**: each `BillingCode` carries `status` (active/hold/discontinued), `mirror_of`, `requires_any_of`, `exclusive_with`, and `payers`; `price_claim()` / `claim_warnings()` enforce them and return `warnings` (mirror pair G-code + CPT, G2214 vs base, 99484 vs base, 99494 without base, APCM add-on without G0556–G0558, holds, discontinued). `rate_info()` is the provenance-carrying rate API; `get_rate`/`price_codes` are compatibility wrappers. The APCM add-ons G0568–G0570 are `hold` (pending written MAC confirmation) and Medicare-only; `evaluate_cocm`/`evaluate_bhi` take `apcm_enrolled=True` (CLI `--apcm-enrolled yes`) to select that pathway, returning the G-code as `eligible_code` and the CPT set as `cpt_alternative`, gated on the CPT midpoint minimum as practice policy (stricter than CMS-1832-F — `APCM_GATE_POLICY`); the base codes G0556–G0558 are catalogued without rates. G0512 is `discontinued` (2026-01-01). Add a rule by setting a field on the code, never by writing a sentence in `notes`. `SOURCES` is the one citation list — every surface (CLI, `--list-codes`, MCP disclaimer) derives from it. `plan_capacity()` / `blended_month_allowance()` (CLI `--capacity-plan N --payer-mix …`, MCP `billing_plan_capacity`) turn an active panel into billable months, BHCM FTE and allowance using `PlanningAssumptions` whose defaults are the workbook's Inputs-sheet values (all labeled illustrative); they reproduce the workbook's CoCM rows and never override per-patient eligibility.

`mcp/cocm_billing_server.py` imports the tracker directly and exposes seven read-only MCP tools (registered in `.mcp.json` as `medsync8-billing`); the plugin vendors both files and CI enforces byte-identity. A change in the script propagates to the CLI, MCP tools, plugin, and audits simultaneously. After any change to billing thresholds or rules, the `billing-auditor` agent (`.claude/agents/billing-auditor.md`) re-runs boundary-value and rule-engine checks; use it proactively.

`scripts/credentialing_alert.py` reads the licensing star-schema workbook and posts a ranked Teams MessageCard. Exit codes: 0 ok, 1 delivery failed, 2 workbook unreadable. Time-dependent logic takes `today: date` as a parameter — never call `date.today()` inside classification logic.

### Legacy modules
`sync_calculator.py` (medication synchronization quantities; tested by `tests/test_sync_calculator.py`) and `med_sync_app_with_stripe.py` (old Streamlit app with Supabase/Stripe) predate the workbench and are not part of either server path.

## Key Conventions

- **Tool IDs** (`policy`, `supervision`, `lecture`, `chat`, `documentation`) are the central organizing concept. They're defined in `src/constants.js` (TOOLS array, TOOL_COLORS, QUICK_PROMPTS, TEMPLATE_LIBRARY) and mirrored in `server.js` SYSTEM_PROMPTS, `backend/prompts.py` SYSTEM_PROMPTS, the Pydantic `Literal` in `backend/server.py` ChatRequest, and `frontend/src/prompts.js` (TOOLS, TOOL_COLORS, SYSTEM_PROMPTS, QUICK_PROMPTS — the RAG `App.jsx` indexes `QUICK_PROMPTS[tool]`, so every tool needs an entry). Add new tools in **all five places**; `backend/tests/test_prompt_tool_sync.py` fails if the frontend mirror drifts from the backend.
- **TOOL_MAP** in `constants.js` provides O(1) lookups; use it instead of `TOOLS.find()`.
- **ERROR_PREFIX** (`⚠️`) in `constants.js` is the shared sentinel for error messages — used in `App.jsx` and `MessageBubble.jsx` to detect error state.
- **Streaming callbacks** (`sendMessage`) use `setConversations` functional updaters to avoid capturing stale `conversations` in the dependency array — this prevents callback recreation on every streaming chunk.
- Backend tests use `StubEmbedder` and `StubAnthropic` from `conftest.py` — no network calls needed. New external dependencies get a stub, not a live call.
- Python imports use relative form within the backend package (e.g., `from .audit import ChatAuditContext`).
- Billing scripts carry decision-support disclaimers and rate-confidence labels (`portal_verified`, `verified_primary`, `verified_secondary`, `estimated`; `_CONFIDENCE_RANK` orders them and the weakest line governs a claim) — never remove them or upgrade a label without a verifying source; `verified_primary` means read or computed from the payer's published primary file with the file and date in `source`. Boundary-test billing edges (35/36, 30/31, target+15/+16, 19/20) after eligibility changes.
- File naming for user-facing artifacts: hyphens, never underscores.

## AI-Agent Governance

This repo carries an instruction-file layer that applies to all coding agents: `.github/copilot-instructions.md` (repository-wide baseline, versioned), `AGENTS.md` (operational guide, hard boundaries, when-blocked rules), and path-scoped `.github/instructions/*.instructions.md` (actions, python, docs, tests — these win for their paths). Do not modify any of them unless the task is specifically an instructions update. Key hard rules: no PHI anywhere including fixtures and `corpus/`; no new unpinned Actions (full-length SHA pins only); synthetic test data only.

## Security Notes

- **Express proxy**: Set `ALLOWED_ORIGIN` in production (defaults to localhost). `trust proxy 1` is set — verify your proxy hop count matches your infra.
- **FastAPI auth**: Set `CF_ACCESS_TEAM_DOMAIN` + `CF_ACCESS_AUD` for Cloudflare Access JWT validation. Without these, all endpoints are publicly accessible (dev only). `/api/audit/recent` additionally requires membership in `AUDIT_ADMIN_EMAILS` (comma-separated allowlist) — with Access on but no allowlist set, the endpoint fails shut (403). `/api/health` attests `access_enforced: true` when Access is on but never advertises when it's off.
- **Audit salt**: Set `AUDIT_SALT` env var in production to a random secret. Without it, audit hashes use a default salt (warning is logged at import).
- **ANTHROPIC_API_KEY**: Express server will exit at startup if missing. FastAPI logs a warning.

## Environment Variables

Required: `ANTHROPIC_API_KEY`. See `.env.example` for all options. Copy to `.env` for local development. The Express server reads it via `dotenv/config`; the FastAPI backend reads it directly from `os.environ`. Upstream relay bounds (FastAPI): `ANTHROPIC_TIMEOUT_SECONDS` (default 180), `ANTHROPIC_MAX_RETRIES` (2), `OPENAI_TIMEOUT_SECONDS` (30), `OPENAI_MAX_RETRIES` (2) — every outbound relay in the backend is time-bounded; keep it that way. Billing rate overrides: `RATE_OVERRIDES_JSON` (per payer, with confidence + source) and the legacy `WI_MEDICAID_RATES_JSON` shorthand. Credentialing alert: `CREDENTIALING_WORKBOOK`, `TEAMS_WEBHOOK_URL`, `TEAMS_CHANNEL_WEBHOOK`.

## Azure Deployment (Container Apps)

Infrastructure lives in `azure/main.bicep`. The GitHub Actions workflow `.github/workflows/deploy-azure.yml` builds the image, pushes to GHCR, and deploys via Bicep on every push to `main`. The `production` environment gates deployment.

### One-time setup

```bash
# 1. Create a resource group
az group create -n medsync8-rg -l eastus

# 2. Create a service principal scoped to that group
az ad sp create-for-rbac \
  --name medsync8-deploy \
  --role Contributor \
  --scopes /subscriptions/<SUB_ID>/resourceGroups/medsync8-rg \
  --sdk-auth
# Paste the JSON output as the AZURE_CREDENTIALS GitHub secret.

# 3. Create a GitHub PAT with read:packages scope for GHCR pull at runtime.
#    Store it as the GHCR_PULL_TOKEN GitHub secret.
```

### GitHub Actions secrets & variables

| Name | Kind | Value |
|---|---|---|
| `AZURE_CREDENTIALS` | Secret | Service principal JSON from step 2 |
| `ANTHROPIC_API_KEY` | Secret | `sk-ant-...` |
| `AUDIT_SALT` | Secret | Random 64-char hex |
| `GHCR_PULL_TOKEN` | Secret | GitHub PAT with `read:packages` |
| `AZURE_RESOURCE_GROUP` | Variable | `medsync8-rg` |
| `ALLOWED_ORIGINS` | Variable | `https://your-frontend.azurestaticapps.net` |
| `CF_ACCESS_TEAM_DOMAIN` | Variable | optional — Cloudflare Access domain |
| `CF_ACCESS_AUD` | Variable | optional — Cloudflare Access AUD tag |

### Manual deploy (without GitHub Actions)

```bash
cp azure/parameters.example.json azure/parameters.json
# Edit azure/parameters.json — fill in all placeholder values.
az deployment group create \
  -g medsync8-rg \
  --template-file azure/main.bicep \
  --parameters azure/parameters.json
```

### What gets deployed
- **Log Analytics workspace** — Container Apps log sink (90-day retention)
- **Key Vault + user-assigned managed identity** — runtime secret source; GitHub secrets seed the vault at deploy time, and the Container App reads them via `keyVaultUrl` references (Key Vault Secrets User role), so secret values never sit in Container Apps configuration
- **Storage account + Azure Files share** — persistent `/data` volume for corpus and audit log
- **Container Apps environment** — shared compute plane
- **Container App** — FastAPI backend, 1 vCPU / 2 GiB, scales 0→3 replicas on HTTP traffic

HIPAA note: Azure offers BAA agreements (see Microsoft HIPAA documentation). Enable at the subscription level before storing any PHI.

## Further Documentation

`docs/USER_GUIDE.md` (end-user guide: web app, scripts, troubleshooting) · `RUNBOOK.md` (Fly.io ops + PHI boundary) · `backend/README.md` (backend specifics).
