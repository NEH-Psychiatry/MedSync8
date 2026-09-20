---
applyTo: "tests/**,backend/tests/**,frontend/src/__tests__/**,frontend/src/test/**,**/test_*.py,**/*_test.py,**/*.test.jsx,**/*.test.js"
---

# Test and Fixture Rules

- Synthetic data only. No PHI, no real patient or provider identifiers, no real dates of service, no payer/member identifiers, no production data — ever, including "anonymized" excerpts of real records.
- Fixture names and contents must be obviously synthetic (e.g., `Patient Test-Alpha`, NPI `1000000004` style checksummed test values, dates in a declared fake range).
- No secrets or tokens in fixtures, even expired ones. Use placeholder patterns like `SECRET_REDACTED_FOR_TESTS`.
- Deterministic tests: seed randomness, freeze time where behavior is time-dependent, no network calls — backend tests stub the embedder and must keep working without model downloads or external services.
- Auth tests exercise `backend/auth.py` with synthetic JWTs and keys only; never a real Cloudflare Access token.
- Every bug fix ships with a regression test that fails on the old code.
- Keep the prompt/tool sync test (`backend/tests/test_prompt_tool_sync.py`) passing whenever `backend/prompts.py` or `frontend/src/prompts.js` changes — it is the contract between the two apps.
- Do not weaken or delete an existing assertion to make a test pass; fix the code or escalate the conflict.
