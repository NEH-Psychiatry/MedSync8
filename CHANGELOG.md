# Changelog

All notable changes to MedSync8 are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- `POST /api/chat/stream` on the FastAPI backend: a Server-Sent Events route
  that performs retrieval first, emits one `citations` frame, then `text`
  deltas from the Anthropic streaming API, then `done`. Thinking blocks are
  dropped. The route shares the request schema, the Cloudflare Access gate,
  the model configuration, and the hash-only audit path with `/api/chat`.
- `ANTHROPIC_TIMEOUT_SECONDS` (default 120) bounds every Anthropic call from
  the backend; for streams it caps the wait for each chunk.
- Frontend streaming: `streamBackend` in `frontend/src/lib/api.js` consumes
  the SSE route with `fetch` and `ReadableStream`, and `useChat` renders
  citations as soon as their frame arrives, then appends text deltas. The
  hook falls back to `POST /api/chat` when streaming is unavailable.
- Tests: the Anthropic test stub gained a `stream()` method; new backend
  tests cover frame ordering, thinking-block suppression, audit recording,
  error handling, and Cloudflare Access gating on the stream route; a new
  Vitest suite covers the streaming hook and its fallback.
- `CLAUDE.md` with the two-route chat architecture and pointers to
  `AGENTS.md`; this changelog.

### Changed

- The request-validation handler returns the `invalid chat request shape`
  body for `/api/chat/stream` as well as `/api/chat`.
- `backend/README.md` and `RUNBOOK.md` document the streaming route, the
  timeout variable, and the shared audit and auth behavior.

### Unchanged

- `POST /api/chat` keeps its request and response contract.
