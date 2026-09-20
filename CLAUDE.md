# CLAUDE.md

Guidance for Claude Code sessions in this repository. `AGENTS.md` and
`.github/copilot-instructions.md` are the governing instruction files; read
them first. Path-scoped rules live in `.github/instructions/*.instructions.md`.

## Architecture

MedSync8 has two application tracks:

- **Telepsychiatry assistant** (current stack): `frontend/` (React + Vite)
  and `backend/` (FastAPI, local RAG retriever, Anthropic proxy, Cloudflare
  Access JWT auth, hash-only audit log).
- **Legacy Streamlit calculator**: `med_sync_app_with_stripe.py`,
  `sync_calculator.py`, tests in `tests/`.

The backend exposes two chat routes with one request schema
(`ChatRequest`), one Cloudflare Access dependency (`require_access`), and one
audit path (`ChatAuditContext`):

| Route | Response | Notes |
|---|---|---|
| `POST /api/chat` | JSON `{reply, citations, model}` | Non-streaming; unchanged contract |
| `POST /api/chat/stream` | `text/event-stream` | Retrieval first; frames `citations` → `text`* → `done` (or `error`); thinking blocks dropped |

Both routes use `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`, and
`ANTHROPIC_TIMEOUT_SECONDS`. The frontend (`frontend/src/lib/api.js`,
`frontend/src/hooks/useChat.js`) streams by default and falls back to
`/api/chat` only when streaming is unavailable.

## Validation Commands

```bash
python -m pytest backend/tests tests -q
cd frontend && npm run lint && npm test && npm run build
```

## Hard Boundaries

See `AGENTS.md`. In short: no PHI or secrets anywhere, do not weaken the
hash-only audit pattern, do not relax Cloudflare Access verification, keep
the corpus limited to public regulation text, and keep
`backend/tests/test_prompt_tool_sync.py` passing when prompts change.
