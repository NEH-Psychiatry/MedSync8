"""FastAPI backend for the MedSync8 telepsychiatry assistant.

Responsibilities:
  * Hide the Anthropic API key server-side.
  * Retrieve relevant context from a local corpus (RAG).
  * Forward the augmented prompt to Claude and return citations.

Run:
  uvicorn backend.server:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .audit import ChatAuditContext, get_logger as get_audit_logger
from .auth import load_config as load_access_config, require_access, require_admin
from .embedders import build_embedder_from_env
from .prompts import SYSTEM_PROMPTS, VALID_TOOLS
from .retriever import Retriever, format_context

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("medsync8")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "16000"))
# /api/chat is a synchronous handler: an unbounded upstream call would pin a
# worker. 180 s comfortably covers a 16k-token completion with thinking.
ANTHROPIC_TIMEOUT_SECONDS = float(os.environ.get("ANTHROPIC_TIMEOUT_SECONDS", "180"))
ANTHROPIC_MAX_RETRIES = int(os.environ.get("ANTHROPIC_MAX_RETRIES", "2"))
CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
TOP_K = int(os.environ.get("RAG_TOP_K", "4"))
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")


# ---------- lifecycle -------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set — /api/chat will fail")
    if not os.environ.get("CF_ACCESS_AUD"):
        log.warning(
            "CF_ACCESS_AUD not set — authentication is DISABLED. "
            "All endpoints are publicly accessible. Set CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD for production."
        )

    embedder = build_embedder_from_env()
    if embedder is None:
        log.warning("no embedder available — retrieval disabled")
        app.state.retriever = None
    else:
        retriever = Retriever(CORPUS_DIR, embedder)
        retriever.load_or_build()
        app.state.retriever = retriever

    app.state.anthropic = build_anthropic_client()
    yield


def build_anthropic_client() -> anthropic.Anthropic:
    """Anthropic client with an explicit request bound (see ANTHROPIC_TIMEOUT_SECONDS)."""
    return anthropic.Anthropic(
        timeout=ANTHROPIC_TIMEOUT_SECONDS, max_retries=ANTHROPIC_MAX_RETRIES
    )


app = FastAPI(title="MedSync8 Telepsychiatry Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS if o.strip()],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


# ---------- schemas ---------------------------------------------------------


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    tool: Literal["policy", "supervision", "lecture", "chat", "documentation"]
    messages: list[Message] = Field(..., min_length=1, max_length=100)
    use_rag: bool = True


class Citation(BaseModel):
    index: int
    doc_id: str
    chunk_id: int
    score: float


class ChatResponse(BaseModel):
    reply: str
    citations: list[Citation]
    model: str


# ---------- routes ----------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    # Attest enforcement when it's on; never advertise that auth is disabled
    # on this unauthenticated endpoint (test_health_does_not_expose_internals).
    body: dict = {"ok": True}
    if load_access_config() is not None:
        body["access_enforced"] = True
    return body


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, claims: dict = Depends(require_access)) -> ChatResponse:
    if req.tool not in VALID_TOOLS:
        raise HTTPException(400, f"unknown tool: {req.tool}")

    system_prompt = SYSTEM_PROMPTS[req.tool]
    retriever: Retriever | None = app.state.retriever
    citations: list[Citation] = []

    # Grab the last user message once -- used for retrieval and audit hash.
    last_user = next(
        (m.content for m in reversed(req.messages) if m.role == "user"), ""
    )

    with ChatAuditContext(tool=req.tool, user_query=last_user, claims=claims) as audit:
        if req.use_rag and retriever and retriever.ready() and last_user:
            hits = retriever.search(last_user, k=TOP_K)
            if hits:
                system_prompt = (
                    f"{system_prompt}\n\n"
                    "=== RETRIEVED CONTEXT ===\n"
                    f"{format_context(hits)}\n"
                    "=== END CONTEXT ===\n"
                    "Use the context above when relevant. If the user's question "
                    "cannot be answered from the context, say so and answer from "
                    "general expertise, but do NOT fabricate citations."
                )
                citations = [
                    Citation(index=i + 1, doc_id=h.doc_id, chunk_id=h.chunk_id, score=h.score)
                    for i, h in enumerate(hits)
                ]

        try:
            resp = app.state.anthropic.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=system_prompt,
                messages=[m.model_dump() for m in req.messages],
            )
        except anthropic.APIError as e:
            log.error("anthropic API error: %s", e)
            raise HTTPException(502, "upstream AI service error") from e

        text = next((b.text for b in resp.content if b.type == "text"), "")
        audit.set_result(reply_len=len(text), citations=citations)

    return ChatResponse(reply=text, citations=citations, model=ANTHROPIC_MODEL)


@app.get("/api/audit/recent")
def audit_recent(
    limit: int = 50,
    claims: dict = Depends(require_admin),
) -> dict:
    """Return the last N audit events (metadata only -- no query text).

    Admin-only: requires Cloudflare Access AND membership in the
    AUDIT_ADMIN_EMAILS allowlist. With Access enabled but no allowlist
    configured, this endpoint is closed (403) -- fail shut.
    """
    limit = max(1, min(limit, 200))
    events = get_audit_logger().recent(limit=limit)
    return {"count": len(events), "events": events}
