# MedSync8 Telepsychiatry Assistant — Runbook

Operational manual for the RAG-backed telepsychiatry workbench
(`frontend/src/App.jsx` + `backend/server.py`).

> **⚠️ HIPAA / PHI boundary.** This runbook covers the **non-PHI internal demo**
> deployment on Fly.io. Do not enter patient identifiers, diagnoses, or any
> PHI into the chat until all of these are true:
>
> 1. Anthropic BAA in place (enterprise / ZDR tier).
> 2. Embeddings running on the **local** backend (default — no third-party
>    embedding call), **or** an OpenAI BAA if you swap `EMBED_BACKEND=openai`.
> 3. Hosting BAA in place (AWS + BAA, Azure + BAA, or Fly.io Enterprise w/ BAA).
> 4. Cloudflare Access (or equivalent SSO) gating `/api/chat` and
>    `/api/chat/stream` — see
>    "Cloudflare Access" below. **Implemented in code**; still needs to be
>    turned on in the Cloudflare dashboard per environment.
> 5. Audit logging enabled (**implemented** — see "Audit log" below) and
>    shipped to long-term retention storage (6+ years — still TODO).
>    The backend writes hash-only events; no raw queries or replies are
>    persisted.
>
> Until then, this tool is for **general regulatory drafting with public regs
> in the corpus** — not patient-level clinical work.

---

## Architecture in one picture

```
Browser (App.jsx)
  │  POST /api/chat/stream {tool, messages}   → text/event-stream
  │  POST /api/chat        {tool, messages}   → JSON (fallback)
  ▼
FastAPI backend (backend/server.py)
  │
  ├──► Retriever (backend/retriever.py)
  │     ├─ reads corpus/ (MD/TXT/PDF)
  │     ├─ Embedder (local bge-small default, OpenAI optional)
  │     └─ cosine top-k, cached in corpus/index.json (keyed by embedder name)
  │
  ├──► Cloudflare Access JWT verification (backend/auth.py)
  │     └─ enforced when CF_ACCESS_TEAM_DOMAIN + CF_ACCESS_AUD are set
  │
  └──► Anthropic Messages API (claude-opus-4-6)
           using role-specific system prompt + retrieved context;
           bounded by ANTHROPIC_TIMEOUT_SECONDS (default 120)

Frontend is a Vite/React SPA deployed to Cloudflare Pages, fronted by the
same Cloudflare Access application so the UI and both chat routes require SSO.

Both chat routes share one request schema, one audit path, and one Anthropic
configuration. `/api/chat/stream` emits one `citations` frame (retrieval runs
before the model call), then `text` deltas, then `done`; thinking blocks are
never forwarded. The frontend streams by default and falls back to
`/api/chat` whenever streaming fails before any reply text has rendered.
```

---

## Deploy to Fly.io (first time)

```bash
# one-time
brew install flyctl        # or: curl -L https://fly.io/install.sh | sh
fly auth login

# from repo root
fly launch --copy-config --no-deploy --name medsync8-telepsych
fly volumes create corpus_data --region ord --size 1

fly secrets set \
  ANTHROPIC_API_KEY=sk-ant-... \
  ALLOWED_ORIGINS=https://medsync8-telepsych.pages.dev \
  CF_ACCESS_TEAM_DOMAIN=yourteam.cloudflareaccess.com \
  CF_ACCESS_AUD=<application-aud-tag-from-cloudflare>

# Only needed if EMBED_BACKEND=openai (default is local; no OpenAI call)
# fly secrets set OPENAI_API_KEY=sk-...

fly deploy
fly open      # opens the /api/health page
```

The image is ~1GB larger than the pre-phi-ready build because the
`sentence-transformers/bge-small-en-v1.5` weights are prefetched at build
time into `/opt/hfcache`. The Fly machine therefore needs **1 GB RAM**
(`fly.toml` now sets `memory = 1024`).

Expected health response after first boot (corpus will be empty until you sync
files to the volume — see next section):

```json
{
  "ok": true,
  "model": "claude-opus-4-6",
  "rag_enabled": false,
  "corpus_chunks": 0,
  "embedder": "local:sentence-transformers/bge-small-en-v1.5",
  "access_enforced": true
}
```

`access_enforced: true` means both `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD`
are set and `/api/chat` and `/api/chat/stream` will reject requests without a
valid `Cf-Access-Jwt-Assertion` header. In dev, leave them unset to disable
enforcement.

## Deploy updates

```bash
git push           # triggers CI
fly deploy         # rebuilds the image and rolls the machine
```

---

## Corpus management

### Local development

Drop `.md`, `.txt`, or `.pdf` files into `corpus/`. Restart the backend — it
will embed new/changed chunks and write `corpus/index.json`.

### Production (Fly volume)

The container mounts `corpus/` from a persistent volume at `/data/corpus`.
To add documents:

```bash
# List what's on the volume
fly ssh console -C "ls -la /data/corpus"

# Upload a single file
fly ssh sftp shell
> cd /data/corpus/federal
> put local_policy.pdf
> quit

# Or rsync a whole folder
fly ssh console -C "mkdir -p /data/corpus/state/tx"
rsync -av ./state_regs/tx/ root@medsync8-telepsych.fly.dev:/data/corpus/state/tx/ \
  -e "ssh -o ProxyCommand='fly ssh console --stdio'"
```

Then restart so the retriever re-indexes:

```bash
fly apps restart medsync8-telepsych
```

With the default `EMBED_BACKEND=local`, embedding cost is **zero** (runs on
CPU inside the Fly machine; ~30s for a 200-doc corpus on first boot).
With `EMBED_BACKEND=openai`, cost is ~$0.02 per 1M tokens with
`text-embedding-3-small` — well under a dollar for a typical 200-doc corpus.

If you switch backends, the retriever detects the change (cache key includes
the embedder name) and re-embeds the whole corpus automatically. Vectors from
different models are never mixed.

### Nuking the cache

If embeddings look stale (e.g. you changed the chunker):

```bash
fly ssh console -C "rm /data/corpus/index.json && kill 1"
```

---

## Secrets rotation

All secrets live in Fly. To rotate:

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-NEW
fly secrets set OPENAI_API_KEY=sk-NEW               # only if EMBED_BACKEND=openai
fly secrets set CF_ACCESS_AUD=<new-app-aud>         # if you recreate the CF app
# Fly rolls the machine automatically after `secrets set`.
```

**Never** commit `.env` files or paste keys into chat messages. `.env`,
`frontend/.env`, and `corpus/index.json` are gitignored.

---

## Common failures and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/health` returns `rag_enabled: false` | Corpus empty or `OPENAI_API_KEY` missing | Add files to the volume; verify secret set |
| Frontend shows "Backend request failed (0)" | CORS or wrong `VITE_API_BASE` | Set `ALLOWED_ORIGINS` to include the frontend URL; rebuild frontend |
| 429 / rate limit from Anthropic | Traffic spike | `fly scale count 2` or add retry-with-backoff |
| Replies appear all at once instead of streaming | A proxy buffers `text/event-stream` | Disable response buffering for `/api/chat/stream` (the backend already sends `X-Accel-Buffering: no`); the UI still completes via the buffered stream |
| Streaming reply ends with `⚠️ Error` after partial text | Upstream stream dropped or `ANTHROPIC_TIMEOUT_SECONDS` hit between chunks | Check Anthropic status; raise `ANTHROPIC_TIMEOUT_SECONDS` if chunks are legitimately slow |
| Retriever returns nothing useful | Query wording mismatch | Check chunk content: `fly ssh console -C "cat /data/corpus/index.json \| jq '.chunks[0]'"` |
| `pypdf` extracts empty text from a PDF | Scanned / image-only PDF | OCR locally (e.g. `ocrmypdf`) before uploading |
| High memory use | Many large PDFs indexed at once | Upgrade VM: `fly scale memory 1024` |

## Monitoring

Fly built-ins:

```bash
fly logs                   # live logs
fly status                 # machine health
fly dashboard              # metrics in browser
```

Add application-level metrics (optional next step): wrap `/api/chat` and
`/api/chat/stream` with a latency histogram + error counter and push to a
Prometheus-compatible endpoint, or use Fly's built-in metrics.

---

## Embedder backend

The embedding model is pluggable via `backend/embedders.py`. Selection is
driven by env vars:

| Var | Default | Options |
|---|---|---|
| `EMBED_BACKEND` | `local` | `local` \| `openai` |
| `LOCAL_EMBED_MODEL` | `sentence-transformers/bge-small-en-v1.5` | any Sentence-Transformers model id |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | any OpenAI embedding model |
| `OPENAI_API_KEY` | _(unset)_ | required only when `EMBED_BACKEND=openai` |

The local backend loads the model from `/opt/hfcache` at container start
(prefetched during the Docker build — no network needed at runtime). Vectors
are L2-normalized, so cosine similarity == dot product.

To switch backends without a redeploy:

```bash
fly secrets set EMBED_BACKEND=openai OPENAI_API_KEY=sk-...
# machine rolls; retriever notices embedder change on boot and re-indexes
```

---

## Cloudflare Access (SSO gating)

`backend/auth.py` verifies the Cloudflare Access JWT that Cloudflare adds as
`Cf-Access-Jwt-Assertion` on every request. It fetches the team's JWKS,
caches it, and checks `iss`, `aud`, `exp`, and signature. The dependency is
wired on `/api/chat`, `/api/chat/stream`, and `/api/audit/recent` (health
stays public for probes).

**One-time setup:**

1. Cloudflare dashboard → **Zero Trust** → **Access** → **Applications** →
   **Add application** → **Self-hosted**.
2. Set the application domain to your Pages domain (e.g.
   `medsync8-telepsych.pages.dev`) **and** the Fly API domain
   (e.g. `medsync8-telepsych.fly.dev`). Both must be in the same application
   so the JWT covers both hops.
3. Policy: allow emails in your team (e.g. `@nehpsychiatry.com`) via Google
   Workspace or any IdP.
4. Copy the **Application Audience (AUD) Tag** and your team domain
   (e.g. `nehpsychiatry.cloudflareaccess.com`).
5. Set as Fly secrets:

   ```bash
   fly secrets set \
     CF_ACCESS_TEAM_DOMAIN=nehpsychiatry.cloudflareaccess.com \
     CF_ACCESS_AUD=<aud-tag>
   ```

6. Confirm `GET /api/health` shows `access_enforced: true`. Hitting
   `/api/chat` or `/api/chat/stream` without logging in should now return 401.

**Bypass for local dev / CI:** leave both env vars unset. `require_access`
becomes a no-op. Tests in `backend/tests/test_auth.py` exercise both modes.

---

## Frontend — Cloudflare Pages

The frontend (`frontend/`) is a Vite/React SPA deployed to Cloudflare Pages.

**One-time setup:**

1. Cloudflare dashboard → **Workers & Pages** → **Create application** →
   **Pages** → connect the GitHub repo.
2. Project name: `medsync8-telepsych` (matches `frontend/wrangler.toml`).
3. Framework preset: **Vite**. Build command: `npm run build`. Output
   directory: `dist`. Root directory: `frontend`.
4. Environment variable: `VITE_API_BASE=https://medsync8-telepsych.fly.dev`.
5. Add the Pages domain to the same Cloudflare Access application as the API.

**Auto-deploy from GitHub Actions:** `.github/workflows/deploy-pages.yml`
pushes a build to Pages on every merge to `main`. Required repo secrets:

- `CLOUDFLARE_API_TOKEN` — Cloudflare → My Profile → API Tokens → Create
  token with "Pages: Edit" permission for the account.
- `CLOUDFLARE_ACCOUNT_ID` — Cloudflare dashboard sidebar.

Optional repo variable (not a secret): `VITE_API_BASE` if you want the CI
build to embed a specific API URL.

Local preview:

```bash
cd frontend
npm ci
VITE_API_BASE=http://localhost:8000 npm run dev
```

---

## Audit log

Every `/api/chat` and `/api/chat/stream` request produces one JSON line in
`/data/audit.log` (configurable via `AUDIT_LOG_PATH`) with:

```json
{
  "ts": "2026-04-18T20:41:12.193+00:00",
  "event": "chat",
  "user": "clinician@nehpsychiatry.com",
  "tool": "policy",
  "query_hash": "a3f19c2d8e0b4716",
  "query_len": 142,
  "reply_len": 1834,
  "citations": 3,
  "top_doc": "dea_ryan_haight.md",
  "latency_ms": 1124,
  "status": "ok"
}
```

**What is NOT in the log:** the raw user message, the model's reply, any
exception message. Only metadata and a salted SHA-256 truncated to 16 hex
chars. Rotating `AUDIT_SALT` makes old hashes unlinkable to new ones.

Streamed exchanges are recorded identically. `reply_len` is set when the
stream completes; a stream that fails midway (or a client that disconnects)
is written with `status: "error"` and `reply_len: 0`.

### Recent events endpoint

`GET /api/audit/recent?limit=50` returns the in-memory tail (last 200
events) as JSON. Gated by Cloudflare Access — restrict with a dedicated
Access policy (e.g. `admin@nehpsychiatry.com` only) if you want to
separate admins from clinicians.

### Long-term retention (6+ years)

`/data/audit.log` persists across deploys because it lives on the
`corpus_data` volume. For HIPAA retention, pipe it off-box. Options:

- **Cloudflare Logpush** if you front the app with Cloudflare (simplest).
- **Fly log shipper** to Datadog / S3 / Loki (`fly.toml` + a shipper).
- **Cron job** that rsyncs `/data/audit.log` to a BAA-covered S3 bucket
  daily, then truncates locally.

Until one of these is wired, the log is only as durable as the Fly
volume. Don't rely on it for compliance.

---

## One-command setup

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export CF_ACCESS_TEAM_DOMAIN=nehpsychiatry.cloudflareaccess.com
export CF_ACCESS_AUD=<aud-tag-from-cf-dashboard>
export ALLOWED_ORIGINS=https://medsync8-telepsych.pages.dev
export AUDIT_SALT="$(openssl rand -hex 32)"

bash scripts/setup_prod.sh
```

This idempotent script creates the Fly app + volume if missing, stages
all secrets, deploys, and verifies `/api/health` reports
`access_enforced: true`. Safe to re-run. It does NOT create the
Cloudflare Access application or the Pages project — do those in the
dashboard once, following the steps in the two sections above.

---

## HIPAA hardening checklist (before PHI traffic)

- [ ] Anthropic enterprise BAA signed, Zero Data Retention enabled.
- [x] **Embeddings run locally (bge-small-en-v1.5) by default — no embedding
      data leaves the container.** OpenAI path remains available for teams
      that have (or will sign) a BAA.
- [ ] Hosting migrated to BAA-covered tier (AWS + BAA, Azure, Fly Enterprise).
- [x] **SSO gating wired in code (Cloudflare Access JWT verification on
      `/api/chat` and `/api/chat/stream`).** Remaining: create the Cloudflare Access application and
      set `CF_ACCESS_TEAM_DOMAIN` / `CF_ACCESS_AUD` secrets per environment.
- [x] **Hash-only audit log (`backend/audit.py`) records timestamp, user
      identity from the Access JWT, tool, salted query hash, lengths, and
      latency.** No raw content stored. Remaining: ship `/data/audit.log`
      to a 6+ year retention target (Logpush → S3, Datadog Archive, etc.).
- [ ] Breach-notification plan documented.
- [ ] Minimum-necessary: strip session history older than N days.
- [ ] Corpus volume encrypted at rest (Fly volumes are encrypted by default;
      verify for other hosts).
- [ ] Annual risk assessment on file.

---

## On-call pager notes

Primary owner: @cvassat
Backup: _TBD_

P0 (app down): check `fly status`, then `fly logs`. Most common cause is an
expired API key — `fly secrets list` to check recency, rotate if unsure.

P1 (wrong answers / no citations): verify `corpus_chunks > 0` at `/api/health`.
If zero, the volume is empty or `OPENAI_API_KEY` is missing.

P2 (slow responses): check Anthropic status page; `fly scale count 2` to
parallelize if traffic is up.
