---
name: run-medsync8
description: Run, test, and smoke-test the MedSync8 repo — the legacy Streamlit medication sync calculator plus the FastAPI/RAG backend and React frontend of the telepsychiatry assistant. Use when asked to "run medsync", "start the app", "test medsync", "run the backend tests", or "smoke test".
---

MedSync8 holds two application tracks (see `README.md`):

1. **Legacy Streamlit medication sync calculator** — `med_sync_app_with_stripe.py` (UI) + `sync_calculator.py` (pure business logic). Supabase auth, Stripe payment link.
2. **Telepsychiatry assistant** — `backend/` (FastAPI + RAG retriever + Anthropic proxy) and `frontend/` (React + Vite).

The smoke driver in this skill covers track 1 end-to-end. Track 2 is covered by its own test suites (commands below). Streamlit renders client-side over WebSocket, so the driver verifies the server headlessly via HTTP while unit tests exercise `calculate_sync_quantities` directly.

All paths below are relative to the project root.

## Prerequisites

```bash
pip install --ignore-installed pyjwt   # Debian PyJWT has no RECORD file; pip aborts without this
pip install -r requirements.txt
pip install pytest flake8
```

## Run (agent path) — smoke script for the Streamlit calculator

Installs deps, runs the calculator unit tests, launches Streamlit headless, verifies `/_stcore/health`, `/` and `/_stcore/host-config`, then stops it:

```bash
.claude/skills/run-medsync8/smoke.sh
```

Optional port argument (default 8501):

```bash
.claude/skills/run-medsync8/smoke.sh 8502
```

The script sets dummy `SUPABASE_URL`, `SUPABASE_KEY`, `STRIPE_PAYMENT_LINK` if unset, so it works without real credentials. The login page renders; auth calls would fail against the dummy project, which is expected.

Exit code 0 = all checks passed. Non-zero = the failing check is printed.

## Direct invocation — calculator logic

Most calculator PRs touch `sync_calculator.py`. Its tests import it directly (no Streamlit, no Supabase, no env vars needed):

```bash
python -m pytest tests -q
```

Lint the root Python files:

```bash
flake8 med_sync_app_with_stripe.py sync_calculator.py tests/
```

## Backend and frontend (telepsychiatry assistant)

```bash
pip install -r backend/requirements-test.txt   # stub embedder; skips torch
python -m pytest backend/tests -q
```

```bash
cd frontend && npm ci && npm run test && npm run build
```

Run the backend locally with `uvicorn backend.server:app --reload --port 8000` (copy `backend/.env.example` to `backend/.env` first).

## Run (human path) — interactive Streamlit

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-anon-key"
export STRIPE_PAYMENT_LINK="https://buy.stripe.com/your-link"
streamlit run med_sync_app_with_stripe.py
```

Opens `http://localhost:8501`. Login/signup need a real Supabase project.

## Gotchas

- **Streamlit is a WebSocket SPA.** `curl` gets the HTML shell only. You cannot fill forms over HTTP. `/_stcore/health` returning `ok` plus HTTP 200 on `/` confirms the server started and the script imported without Python errors.
- **App entry point is guarded.** `med_sync_app_with_stripe.py` runs everything from `main()` under `if __name__ == "__main__"`, and `init_supabase()` imports the Supabase client lazily. Importing the module in tests is safe.
- **`datetime.today()` includes time.** `sync_calculator.py` normalizes today to midnight. When writing tests with date math, expected values must use the same normalization or they will be off by up to a day.
- **PyJWT conflict on Debian.** `pip install -r requirements.txt` fails with "Cannot uninstall PyJWT 2.7.0, RECORD file not found". Run `pip install --ignore-installed pyjwt` first. The smoke script and the SessionStart hook already do this.
- **No `origin/HEAD` by default.** If git commands fail with "ambiguous argument 'origin/HEAD'", run `git remote set-head origin main`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'streamlit'` | `pip install -r requirements.txt` |
| `Cannot uninstall PyJWT 2.7.0, RECORD file not found` | `pip install --ignore-installed pyjwt` then retry |
| `Missing SUPABASE_URL or SUPABASE_KEY` and app stops | Set env vars, or use the smoke script which provides dummy values |
| Tests off by 1 day on unit counts | Normalize "today" to midnight in expected-value math, as `sync_calculator.py` does |
| `flake8: F401 ... imported but unused` in the app | Remove the import; the app only needs `create_client` from `supabase` |
