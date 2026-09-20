import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChat } from "../hooks/useChat";

// A hand-driven SSE body: tests push frames one at a time to assert ordering.
function sseStream() {
  const encoder = new TextEncoder();
  let controller;
  const stream = new ReadableStream({
    start(c) {
      controller = c;
    },
  });
  return {
    stream,
    push: (event, data) =>
      controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => controller.close(),
  };
}

function streamResponse(sse) {
  return { ok: true, status: 200, body: sse.stream, json: vi.fn() };
}

function jsonResponse(ok, payload, status = 200) {
  return { ok, status, body: null, json: vi.fn().mockResolvedValue(payload) };
}

const CITATION = { index: 1, doc_id: "dea_ryan_haight.md", chunk_id: 0, score: 0.9 };

describe("useChat streaming", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    globalThis.fetch = vi.fn();
  });

  it("renders citations as soon as their frame arrives, then accumulates text deltas", async () => {
    const sse = sseStream();
    globalThis.fetch.mockResolvedValueOnce(streamResponse(sse));
    const onError = vi.fn();

    const { result } = renderHook(() => useChat({ activeTool: "policy", onError }));

    let pending;
    act(() => {
      pending = result.current.sendMessage("Draft a PDMP policy");
    });

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    expect(globalThis.fetch.mock.calls[0][0]).toMatch(/\/api\/chat\/stream$/);
    expect(JSON.parse(globalThis.fetch.mock.calls[0][1].body)).toEqual({
      tool: "policy",
      messages: [{ role: "user", content: "Draft a PDMP policy" }],
      use_rag: true,
    });

    // Citations frame: the reply bubble exists with sources but no text yet.
    await act(async () => sse.push("citations", { citations: [CITATION] }));
    await waitFor(() => expect(result.current.currentConvo).toHaveLength(2));
    expect(result.current.currentConvo[1]).toMatchObject({
      role: "assistant",
      content: "",
      citations: [CITATION],
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.streaming).toBe(true);

    await act(async () => sse.push("text", { delta: "Purpose: " }));
    await waitFor(() => expect(result.current.currentConvo[1].content).toBe("Purpose: "));

    await act(async () => sse.push("text", { delta: "check the PDMP." }));
    await waitFor(() =>
      expect(result.current.currentConvo[1].content).toBe("Purpose: check the PDMP."),
    );

    await act(async () => {
      sse.push("done", { model: "test", reply_len: 24 });
      sse.close();
      await pending;
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.streaming).toBe(false);
    expect(result.current.currentConvo[1]).toMatchObject({
      content: "Purpose: check the PDMP.",
      citations: [CITATION],
    });
    expect(onError).not.toHaveBeenCalled();
  });

  it("falls back to POST /api/chat when the streaming endpoint is unavailable", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(jsonResponse(false, { detail: "Not Found" }, 404))
      .mockResolvedValueOnce(
        jsonResponse(true, { reply: "sync reply", citations: [CITATION], model: "test" }),
      );

    const { result } = renderHook(() => useChat({ activeTool: "chat" }));
    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(globalThis.fetch.mock.calls[0][0]).toMatch(/\/api\/chat\/stream$/);
    expect(globalThis.fetch.mock.calls[1][0]).toMatch(/\/api\/chat$/);
    expect(result.current.currentConvo[1]).toMatchObject({
      role: "assistant",
      content: "sync reply",
      citations: [CITATION],
    });
    expect(result.current.loading).toBe(false);
  });

  it("keeps partial text and reports a mid-stream error without falling back", async () => {
    const sse = sseStream();
    globalThis.fetch.mockResolvedValueOnce(streamResponse(sse));
    const onError = vi.fn();

    const { result } = renderHook(() => useChat({ activeTool: "chat", onError }));
    await act(async () => {
      const pending = result.current.sendMessage("hello");
      sse.push("citations", { citations: [] });
      sse.push("text", { delta: "partial answer" });
      sse.push("error", { detail: "anthropic error: upstream reset" });
      sse.close();
      await pending;
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(result.current.currentConvo[1].content).toBe(
      "partial answer\n\n⚠️ Error: anthropic error: upstream reset",
    );
    expect(onError).toHaveBeenCalledWith("anthropic error: upstream reset");
    expect(result.current.loading).toBe(false);
  });

  it("falls back to POST /api/chat on an HTTP error from the streaming route", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(jsonResponse(false, { detail: "anthropic error: upstream" }, 502))
      .mockResolvedValueOnce(jsonResponse(true, { reply: "sync reply", citations: [], model: "test" }));

    const { result } = renderHook(() => useChat({ activeTool: "chat" }));
    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(globalThis.fetch.mock.calls[1][0]).toMatch(/\/api\/chat$/);
    expect(result.current.currentConvo).toHaveLength(2);
    expect(result.current.currentConvo[1].content).toBe("sync reply");
  });

  it("falls back without a duplicate bubble when an error frame arrives before any text", async () => {
    const sse = sseStream();
    globalThis.fetch
      .mockResolvedValueOnce(streamResponse(sse))
      .mockResolvedValueOnce(
        jsonResponse(true, { reply: "sync reply", citations: [CITATION], model: "test" }),
      );

    const { result } = renderHook(() => useChat({ activeTool: "chat" }));
    await act(async () => {
      const pending = result.current.sendMessage("hello");
      sse.push("citations", { citations: [CITATION] });
      sse.push("error", { detail: "anthropic response missing text content" });
      sse.close();
      await pending;
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(result.current.currentConvo).toHaveLength(2);
    expect(result.current.currentConvo[1]).toMatchObject({
      role: "assistant",
      content: "sync reply",
      citations: [CITATION],
    });
  });

  it("shows one error when both routes fail", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(jsonResponse(false, { detail: "missing Cloudflare Access JWT" }, 401))
      .mockResolvedValueOnce(jsonResponse(false, { detail: "missing Cloudflare Access JWT" }, 401));

    const { result } = renderHook(() => useChat({ activeTool: "chat" }));
    await act(async () => {
      await result.current.sendMessage("hello");
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(result.current.currentConvo).toHaveLength(2);
    expect(result.current.currentConvo[1].content).toBe("⚠️ Error: missing Cloudflare Access JWT");
  });
});
