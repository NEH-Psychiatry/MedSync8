# MedSync8

Clinical AI tooling for psychiatric practice, powered by Claude. The repository holds **two application tracks plus a clinical scripts layer**:

1. **Psychiatry AI Workbench** — root `src/` (React + Vite) with an Express proxy (`server.js`). Streams responses, saves and exports drafts, runs locally.
2. **Telepsychiatry assistant (production RAG stack)** — `frontend/` (React + Vite, Cloudflare Pages) with `backend/` (FastAPI, local-corpus retrieval with citations, Cloudflare Access auth, hash-only audit log; deployed to Azure Container Apps or Fly.io).
3. **Clinical scripts and MCP tools** — `scripts/` (CoCM/BHI billing tracker, credentialing alert), `mcp/` (billing MCP server), `plugins/` (installable Claude Code plugin).

A legacy Streamlit medication sync calculator (`med_sync_app_with_stripe.py`, `sync_calculator.py`) predates both apps and is kept for reference.

## Repository structure

- `src/`, `server.js`, `vite.config.js` — workbench UI and Express proxy
- `frontend/` — RAG chat UI, prompt/template library, Vitest tests
- `backend/` — API, retrieval, prompts mirror, backend tests
- `corpus/` — local RAG source documents (public federal regulation text only)
- `scripts/`, `mcp/`, `plugins/` — billing and credentialing tooling
- `tests/` — root tests (billing tracker, MCP tools, credentialing alert, plugin sync, legacy calculator)
- `azure/`, `.github/workflows/` — infrastructure and CI/CD
- `docs/` — user guide, enterprise development guide, MAC inquiry drafts

## Quick start: Psychiatry AI Workbench

Requires Node.js 20+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
npm install
cp .env.example .env      # add ANTHROPIC_API_KEY
npm run dev               # Vite on :5173, Express proxy on :3001
```

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | **(Required)** Your Anthropic API key |
| `PORT` | Express port (default: 3001) |
| `ALLOWED_ORIGIN` | CORS origin (default: http://localhost:5173) |

Tools: Policy Generator, Supervision Tools, Lecture Builder, Clinical Consult, and Documentation; a template library, save/export to PDF, and localStorage persistence. The API key never leaves the server — the proxy validates tool names, sanitizes messages, and rate-limits (20 req/min).

## Quick start: telepsychiatry assistant (frontend + backend)

### Backend

```bash
cd backend
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.server:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.example .env      # VITE_API_BASE → the backend URL
npm ci
npm run dev
```

Frontend defaults to `http://localhost:5173`, backend to `http://localhost:8000`. See `RUNBOOK.md` for deployment and the PHI boundary (no PHI until BAA + local embeddings are confirmed).

## Quick start: legacy Streamlit medication sync calculator

```bash
cp .env.example .env      # Supabase/Stripe values in the root .env
pip install -r requirements.txt
streamlit run med_sync_app_with_stripe.py
```

## Open in VS Code

The repository ships a shared workspace configuration under `.vscode/`:

- **Recommended extensions** — Python, Pylance, ESLint, Prettier, and Vitest Explorer.
- **Debug configurations** — `Backend: FastAPI (uvicorn)`, `Frontend: Vite dev server`, `Backend: pytest`, and a `Full stack: backend + frontend` compound.
- **Tasks** — install, lint, test, and build tasks per app, plus `All checks (CI parity)`.
- **Test discovery** — pytest is preconfigured against `backend/tests`; create the venv at `backend/.venv` and VS Code picks it up.

A dev container (`.devcontainer/`) provisions Python 3.11 + Node 20 with all three apps' dependencies preinstalled, for Codespaces or the Dev Containers extension.

## Testing

```bash
python -m pytest backend/tests tests -q     # backend + root suites (what CI runs)
npm run build                               # workbench build
cd frontend && npm run lint && npm test && npm run build
python -m unittest discover tests -v        # legacy calculator only
```

## Further documentation

`CLAUDE.md` (architecture and conventions) · `docs/USER_GUIDE.md` · `docs/enterprise-development.md` · `RUNBOOK.md` · `CHANGELOG.md` · `AGENTS.md` and `.github/copilot-instructions.md` (AI-agent governance)

---

*Nuestra Esperanza Health · AI-assisted drafts require clinical review before use. Billing outputs are decision-support only.*
