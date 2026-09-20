const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * Thrown when streaming cannot be used at all (no ReadableStream support,
 * endpoint missing on the backend, or the request never reached it).
 * Callers fall back to the non-streaming `callBackend` on this error only.
 */
export class StreamUnavailableError extends Error {
  constructor(message) {
    super(message);
    this.name = "StreamUnavailableError";
  }
}

function chatRequestInit(tool, messages, signal) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, messages, use_rag: true }),
    signal,
  };
}

async function errorFromResponse(res) {
  const err = await res.json().catch(() => null);
  return new Error(err?.detail ?? `Backend request failed (${res.status})`);
}

export async function callBackend(tool, messages) {
  const res = await fetch(`${API_BASE}/api/chat`, chatRequestInit(tool, messages));

  if (!res.ok) throw await errorFromResponse(res);

  return res.json();
}

// Parse one SSE frame ("event: x\ndata: {...}") into { event, data }.
function parseFrame(raw) {
  let event = "message";
  const dataLines = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * Stream a reply from `POST /api/chat/stream` (Server-Sent Events).
 *
 * Frame order from the backend is `citations` → `text`* → `done`, or `error`
 * if the upstream call fails mid-stream. `onCitations(citations)` fires once
 * as soon as the citations frame arrives; `onText(delta, replySoFar)` fires
 * per text delta. Resolves with `{ reply, citations, model }`.
 */
export async function streamBackend(tool, messages, { onCitations, onText, signal } = {}) {
  if (typeof ReadableStream === "undefined" || typeof TextDecoder === "undefined") {
    throw new StreamUnavailableError("streaming not supported in this browser");
  }

  let res;
  try {
    res = await fetch(`${API_BASE}/api/chat/stream`, chatRequestInit(tool, messages, signal));
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new StreamUnavailableError(e?.message ?? "network error");
  }

  if (!res.ok) {
    // An older backend without the endpoint; everything else is a real error
    // that the non-streaming route would reproduce.
    if ([404, 405, 501].includes(res.status)) {
      throw new StreamUnavailableError(`streaming endpoint unavailable (${res.status})`);
    }
    throw await errorFromResponse(res);
  }
  if (typeof res.body?.getReader !== "function") {
    throw new StreamUnavailableError("streaming response body unsupported");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reply = "";
  let citations = [];
  let model;
  let frames = 0;
  let done = false;

  for (;;) {
    const { value, done: eof } = await reader.read();
    buffer += (eof ? decoder.decode() : decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");

    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = parseFrame(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
      if (!frame) continue;
      frames += 1;

      switch (frame.event) {
        case "citations":
          citations = frame.data.citations ?? [];
          onCitations?.(citations);
          break;
        case "text": {
          const delta = frame.data.delta ?? "";
          reply += delta;
          onText?.(delta, reply);
          break;
        }
        case "done":
          model = frame.data.model;
          done = true;
          break;
        case "error":
          throw new Error(frame.data.detail ?? "streaming failed");
        default:
          break;
      }
    }
    if (eof || done) break;
  }

  if (!done) {
    if (frames === 0) throw new StreamUnavailableError("stream ended before any frame");
    throw new Error("stream ended before completion");
  }

  return { reply, citations, model };
}
