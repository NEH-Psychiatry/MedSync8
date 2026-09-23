# MedSync8

MedSync8 currently contains **two application tracks**:

1. **Legacy Streamlit medication sync calculator**
   - `/med_sync_app_with_stripe.py`
   - `/sync_calculator.py`
2. **Telepsychiatry assistant (current app stack)**
   - `/frontend` → React + Vite UI
   - `/backend` → FastAPI + RAG retriever + Anthropic proxy

## Repository structure

- `/backend` — API, retrieval, prompts mirror, backend tests
- `/frontend` — chat UI, prompt/template library, frontend tests
- `/corpus` — local RAG source documents
- `/tests` — legacy calculator unit tests
- `/med_sync_app_with_stripe.py`, `/sync_calculator.py` — legacy Streamlit app

## Open in VS Code

The repository ships a shared workspace configuration under `.vscode/`:

- **Recommended extensions** — Python, Pylance, ESLint, and Vitest Explorer (VS Code offers them on first open).
- **Debug configurations** (Run and Debug panel) — `Backend: FastAPI (uvicorn)`, `Frontend: Vite dev server`, `Backend: pytest`, and a `Full stack: backend + frontend` compound that starts both.
- **Tasks** (Terminal → Run Task) — install, lint, test, and build tasks per app, plus `All checks (CI parity)` mirroring the CI pipeline.
- **Test discovery** — pytest is preconfigured against `backend/tests`. Create the venv at `backend/.venv` and install the test requirements into it — `python -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements-test.txt` — and VS Code picks it up. The quick start below installs `requirements.txt`, which does not include pytest.

A dev container (`.devcontainer/`) provisions Python 3.11 + Node 20 with both apps' dependencies preinstalled, for Codespaces or the Dev Containers extension.

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
cp .env.example .env
npm ci
npm run dev
```

Frontend defaults to `http://localhost:5173`, backend to `http://localhost:8000`.

## Quick start: legacy Streamlit medication sync calculator

```bash
cp .env.example .env
pip install -r requirements.txt
streamlit run med_sync_app_with_stripe.py
```

The root `.env.example` is for this legacy Streamlit path only.

## Testing

### Backend

```bash
python -m pytest backend/tests -q
```

### Frontend

```bash
cd frontend
npm run test
```

### Legacy calculator

```bash
python -m unittest discover tests -v
```
