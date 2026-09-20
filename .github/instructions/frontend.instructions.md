---
applyTo: "frontend/**/*.js,frontend/**/*.jsx,frontend/**/*.css,frontend/**/*.html,src/**/*.js,src/**/*.jsx,src/**/*.css,index.html,server.js,vite.config.js"
---

# Frontend Rules

Two React clients live in this repository and serve different backends. Do not merge or "deduplicate" them: the root workbench cannot render citations and the `frontend/` client cannot stream.

- **Root workbench** (`src/`, `server.js`): React 18 + Vite 8, plain JavaScript. API access in `src/api.js` only (Express proxy `/api/claude`, `/api/claude/stream`). Tools, prompts, and templates live in `src/constants.js`; use `TOOL_MAP` for lookups, `ERROR_PREFIX` (⚠️) as the error sentinel, and `setConversations` functional updaters in streaming callbacks.
- **RAG client** (`frontend/`): React 19 + Vite 7, ESLint, Vitest + Testing Library. Presentational components in `src/components/`, state in `src/hooks/`, API access in `src/lib/api.js` only (FastAPI `/api/chat` via `VITE_API_BASE`). Do not scatter `fetch` calls into components.
- ESLint governs style in `frontend/` — run `npm run lint`; do not request stylistic churn ESLint already covers.
- Never hardcode URLs, API keys, or model names in frontend code — both backends proxy Anthropic precisely so no key ships to the browser.
- Never log, persist, or transmit chat content anywhere except the configured backend API. Saved responses stay in the mechanisms already in place (localStorage); introducing new storage or third-party calls for message content is a security change requiring explicit task scope.
- Prompt/template definitions in `frontend/src/prompts.js` mirror `backend/prompts.py`; keep them in sync and preserve the `test_prompt_tool_sync.py` contract when editing either side. The root workbench mirrors the same tool IDs in `src/constants.js` and `server.js` — five places total.
- Tests: Vitest + Testing Library in `frontend/src/__tests__/`. Behavior changes ship with a test. `npm test` and `npm run build` must pass in `frontend/`; `npm run build` must pass at the root.
- Accessibility: interactive elements are keyboard-reachable with accessible names; don't replace buttons with clickable divs.
- Do not add dependencies without a one-line justification in the PR and a lockfile update via `npm install` (committed `package-lock.json` in each app).
