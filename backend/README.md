# Telepsychiatry Backend (RAG + Anthropic proxy)

FastAPI service that powers `frontend/src/App.jsx`. It:

1. Hides the Anthropic API key server-side (no more browser-exposed keys).
2. Retrieves relevant passages from a local `corpus/` folder via OpenAI embeddings.
3. Appends the retrieved context to the role-specific system prompt and forwards to Claude.
4. Returns the answer plus citation metadata, either as one JSON reply (`/api/chat`) or as a Server-Sent Events stream (`/api/chat/stream`).

## Setup

```bash
cd backend
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...            # used for embeddings only
export CORPUS_DIR=./corpus              # defaults to ./corpus
export ALLOWED_ORIGINS=http://localhost:5173
export ANTHROPIC_TIMEOUT_SECONDS=120    # optional; bounds every Anthropic call
```

## Corpus

Drop `.md`, `.txt`, or `.pdf` files into `corpus/`. On first boot the server:

1. Splits each doc into ~1200-char chunks with 200-char overlap.
2. Embeds chunks with `text-embedding-3-small`.
3. Caches embeddings to `corpus/index.json` (SHA-keyed — unchanged chunks are reused).

Re-running the server after adding/editing docs re-embeds only the changed chunks.

## Run

```bash
uvicorn backend.server:app --reload --port 8000
```

Health check:
```bash
curl http://localhost:8000/api/health
# {"ok":true,"model":"claude-opus-4-6","rag_enabled":true,"corpus_chunks":42}
```

## API

### `POST /api/chat`

```json
{
  "tool": "policy",
  "messages": [{"role": "user", "content": "Draft a Schedule II prescribing policy"}],
  "use_rag": true
}
```

Response:
```json
{
  "reply": "PURPOSE...[1]...PROCEDURES...[2]...",
  "citations": [
    {"index": 1, "doc_id": "dea/ryan-haight.pdf", "chunk_id": 3, "score": 0.82},
    {"index": 2, "doc_id": "tx-medical-board/pdmp.md", "chunk_id": 0, "score": 0.77}
  ],
  "model": "claude-opus-4-6"
}
```

### `POST /api/chat/stream`

Same request body and the same Cloudflare Access gate as `/api/chat`. The response is `text/event-stream`. Retrieval runs first, so the citation list arrives before any model output:

```
event: citations
data: {"citations":[{"index":1,"doc_id":"dea/ryan-haight.pdf","chunk_id":3,"score":0.82}]}

event: text
data: {"delta":"PURPOSE"}

event: text
data: {"delta":"...[1]..."}

event: done
data: {"model":"claude-opus-4-6","reply_len":1834}
```

Rules:

- Exactly one `citations` frame, then zero or more `text` frames, then one `done` frame.
- Only text deltas are forwarded. Thinking blocks are dropped.
- Model, `max_tokens`, system prompt, and message list match `/api/chat`.
- Errors before the first frame are ordinary HTTP errors (401, 422, 502). A failure after streaming starts is sent as a single `error` frame with a `detail` string instead of `done`.
- The exchange is audited exactly like `/api/chat` (hash-only). The reply length is recorded when the stream completes.
- `ANTHROPIC_TIMEOUT_SECONDS` (default 120) bounds the upstream call; for streams it caps the wait for each chunk.

The frontend tries this route first and falls back to `/api/chat` whenever streaming fails before any reply text has rendered (older backend, no `ReadableStream`, network failure, HTTP error, or an `error` frame before the first delta). Once text has rendered, a failure keeps the partial text and appends the error instead.

## Why this design

- **Single-file JSON index** over FAISS/pgvector: zero ops, obvious to debug, plenty fast up to ~10k chunks. Swap out `_cosine_topk` for FAISS when you outgrow it.
- **SHA-keyed chunk cache**: editing one policy doesn't re-embed the whole corpus.
- **Prompts mirrored in `prompts.py` and `frontend/src/prompts.js`**: the two files are intentionally duplicated — backend must run standalone, frontend must show quick-prompt chips without a server round-trip. Keep them in sync by search.
- **Citation indices `[1] [2]`** match what the system prompt tells Claude to emit, and the frontend can render them as links to `doc_id#chunk{chunk_id}`.
- **Streaming as SSE over a plain POST** (not `EventSource`): the browser keeps its JSON request body and Access cookie, and the same frame parser works for `fetch` + `ReadableStream` everywhere.

## Scaling notes

- Swap embeddings for local (e.g. bge-small) if HIPAA disallows sending corpus text to OpenAI.
- For true PHI isolation, run the retriever on a VPC-only box and expose `/api/chat` and `/api/chat/stream` via API Gateway.
