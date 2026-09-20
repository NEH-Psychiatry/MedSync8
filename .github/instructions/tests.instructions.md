---
applyTo: "tests/**,backend/tests/**,frontend/src/__tests__/**,frontend/src/test/**,**/test_*.py,**/*_test.py,**/*.test.jsx,**/*.test.js,**/fixtures/**"
---

# Test and Fixture Rules

- Synthetic data only. No PHI, no real patient or provider identifiers, no real dates of service, no payer/member identifiers, no production data — ever, including "anonymized" excerpts of real records.
- Fixture names and contents must be obviously synthetic (e.g., `Patient Test-Alpha`, `PT-001` style panel IDs, NPI `1000000004` style checksummed test values, dates in a declared fake range).
- No secrets or tokens in fixtures, even expired ones. Use placeholder patterns like `SECRET_REDACTED_FOR_TESTS`.
- No network calls: backend tests use `StubEmbedder` and `StubAnthropic` from `backend/tests/conftest.py`; script tests mock `urllib`; new external dependencies get a stub in `conftest.py`, not a live call behind a marker. Backend tests must keep working without model downloads or external services.
- Auth tests exercise `backend/auth.py` with synthetic JWTs and keys only; never a real Cloudflare Access token.
- Deterministic tests: seed randomness, freeze time where behavior is time-dependent (pass `today: date` parameters rather than calling `date.today()` inside logic — the pattern `scripts/credentialing_alert.py` uses).
- Billing-logic changes ship with boundary-value tests at the CMS thresholds (35/36, 30/31, target+15/+16, 19/20 minutes) and rule-engine assertions; `mcp/evaluation.xml` answers are derived from code in `tests/test_cocm_time_tracker.py`, never hand-transcribed.
- Keep the prompt/tool sync test (`backend/tests/test_prompt_tool_sync.py`) passing whenever `backend/prompts.py` or `frontend/src/prompts.js` changes — it is the contract between the two apps — and the plugin sync test (`tests/test_plugin_sync.py`) passing whenever the tracker or MCP server changes.
- Every bug fix ships with a regression test that fails on the old code.
- Do not weaken or delete an existing assertion to make a test pass; fix the code or escalate the conflict.
