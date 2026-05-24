---
name: run-medsync8
description: Run, test, and smoke-test the MedSync8 Streamlit medication sync calculator app. Use when asked to "run medsync", "start the app", "test medsync", or "smoke test".
---

MedSync8 is a Streamlit web app for calculating medication synchronization schedules with Supabase auth and Stripe payments. It's driven headless via HTTP since Streamlit renders client-side over WebSocket — `curl` verifies the server is alive and serving, while unit tests cover the `calculate_sync_quantities` business logic directly.

All paths below are relative to the project root (`/home/user/MedSync8`).

## Prerequisites

```bash
pip install -r requirements.txt
pip install pytest
```

## Run (agent path) — smoke script

The smoke script installs deps, runs all unit tests, launches the Streamlit server, verifies HTTP health + main page + config endpoint, then stops it. One command:

```bash
.claude/skills/run-medsync8/smoke.sh
```

Optional: pass a port number (default 8501):

```bash
.claude/skills/run-medsync8/smoke.sh 8502
```

The script sets dummy env vars (`SUPABASE_URL`, `SUPABASE_KEY`, `STRIPE_PAYMENT_LINK`) if not already set, so it works without real credentials. The app will start and serve the login page — auth calls will fail against dummy credentials, but the server and UI render correctly.

Exit code 0 = all checks passed. Non-zero = something broke; output shows which check failed.

## Direct invocation — testing the core logic

Most PRs touch `calculate_sync_quantities` in `med_sync_app_with_stripe.py`. Test it directly without launching the server:

```bash
SUPABASE_URL="https://test.supabase.co" SUPABASE_KEY="test-key" python -m pytest tests/ -v
```

The test file mocks `streamlit` and `supabase` at the module level before importing, so no real connections are made.

## Run (human path) — interactive

For local development with real credentials:

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-anon-key"
export STRIPE_PAYMENT_LINK="https://buy.stripe.com/your-link"
streamlit run med_sync_app_with_stripe.py
```

Opens browser to `http://localhost:8501`. Requires real Supabase credentials for login/signup to work.

## Gotchas

- **Streamlit is a WebSocket SPA.** `curl` gets the HTML shell but not rendered content. You cannot fill forms or click buttons via HTTP. The health endpoint (`/_stcore/health`) and HTTP 200 on `/` confirm the server is alive and the app loaded without Python errors.
- **Module-level side effects.** `med_sync_app_with_stripe.py` runs Streamlit widget code at import time (not inside `if __name__ == '__main__'`). Tests must mock `streamlit` and `supabase` and set env vars *before* importing the module.
- **`datetime.today()` includes time.** The app normalizes to midnight via `.replace(hour=0, minute=0, second=0, microsecond=0)`. If you're writing new tests with date math, compute expected values the same way — raw `datetime.today()` will be off by up to a day.
- **PyJWT conflict on Debian.** `pip install` may fail with "Cannot uninstall PyJWT" — fix with `pip install --ignore-installed pyjwt` first, then re-run `pip install -r requirements.txt`.
- **No `origin/HEAD` by default.** If git commands fail with "ambiguous argument 'origin/HEAD'", run `git remote set-head origin main`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'streamlit'` | `pip install -r requirements.txt` |
| `Cannot uninstall PyJWT 2.7.0, RECORD file not found` | `pip install --ignore-installed pyjwt` then retry |
| `Missing SUPABASE_URL or SUPABASE_KEY` and app stops | Set env vars or use the smoke script which provides dummy values |
| Tests fail with `ValueError: not enough values to unpack` | Ensure `st_mock.tabs.return_value = (MagicMock(), MagicMock())` is set before import |
| Tests off by 1 day on unit counts | Use `datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)` for today in expected calculations |
