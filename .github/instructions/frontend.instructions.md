---
applyTo: "frontend/**/*.js,frontend/**/*.jsx,frontend/**/*.css,frontend/**/*.html"
---

# Frontend Rules

- Stack: React 19 + Vite, plain JavaScript (no TypeScript). ESLint governs style — run `npm run lint`; do not request stylistic churn ESLint already covers.
- Keep components small and focused, matching the existing layout: presentational components in `src/components/`, state in `src/hooks/`, API access in `src/lib/api.js` only. Do not scatter `fetch` calls into components.
- All backend access goes through the configured API base (`VITE_API_BASE`). Never hardcode URLs, API keys, or model names in frontend code — the backend proxies Anthropic precisely so no key ships to the browser.
- Never log, persist, or transmit chat content anywhere except the backend API. Saved responses stay in the mechanisms already in place; introducing new storage or third-party calls for message content is a security change requiring explicit task scope.
- Prompt/template definitions in `src/prompts.js` mirror the backend's `backend/prompts.py`; keep the two in sync and preserve the sync test (`test_prompt_tool_sync.py`) contract when editing either side.
- Tests: Vitest + Testing Library in `src/__tests__/`. Behavior changes ship with a test. `npm run test` and `npm run build` must pass.
- Accessibility: interactive elements are keyboard-reachable with accessible names; don't replace buttons with clickable divs.
- Do not add dependencies without a one-line justification in the PR and a lockfile update via `npm install` (committed `package-lock.json`).
