import { useEffect, useRef, useState } from "react";
import { TOOLS } from "../prompts";
import { callBackend, streamBackend, StreamUnavailableError } from "../lib/api";

const EMPTY_CONVERSATIONS = { policy: [], supervision: [], lecture: [], chat: [] };

export function useChat({ activeTool, onError }) {
  const [conversations, setConversations] = useState(EMPTY_CONVERSATIONS);
  const [savedResponses, setSavedResponses] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("saved_responses") ?? "[]");
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // True once the first streamed frame has arrived and a reply bubble exists.
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef(null);

  const currentConvo = conversations[activeTool];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversations, loading]);

  useEffect(() => {
    localStorage.setItem("saved_responses", JSON.stringify(savedResponses));
  }, [savedResponses]);

  async function sendMessage(text, tool = activeTool) {
    if (!text.trim() || loading) return;

    const userMsg = { role: "user", content: text };
    const updated = [...conversations[tool], userMsg];
    setConversations((p) => ({ ...p, [tool]: updated }));
    setInput("");
    setLoading(true);

    // Append against current state, not the pre-request snapshot: if the
    // conversation was cleared while the request was in flight, drop the reply.
    const appendReply = (assistantMsg) =>
      setConversations((p) =>
        p[tool].includes(userMsg) ? { ...p, [tool]: [...p[tool], assistantMsg] } : p,
      );

    // Patch the in-progress streamed reply by id; a no-op if it was cleared.
    const replyId = crypto.randomUUID();
    const updateReply = (patch) =>
      setConversations((p) => {
        const convo = p[tool];
        if (!convo.some((m) => m.id === replyId)) return p;
        return { ...p, [tool]: convo.map((m) => (m.id === replyId ? { ...m, ...patch } : m)) };
      });

    try {
      let started = false;
      let partial = "";
      try {
        const { reply, citations } = await streamBackend(tool, updated, {
          onCitations: (citations) => {
            started = true;
            setStreaming(true);
            appendReply({ id: replyId, role: "assistant", content: "", citations });
          },
          onText: (_delta, replySoFar) => {
            partial = replySoFar;
            updateReply({ content: replySoFar });
          },
        });
        updateReply({ content: reply, citations });
        return;
      } catch (e) {
        if (started) {
          // The reply bubble already exists; keep whatever text arrived.
          onError?.(e.message);
          updateReply({ content: partial ? `${partial}\n\n⚠️ Error: ${e.message}` : `⚠️ Error: ${e.message}` });
          return;
        }
        if (!(e instanceof StreamUnavailableError)) throw e;
        // Streaming is unavailable (old backend, no ReadableStream, network) — fall back.
      }

      const { reply, citations } = await callBackend(tool, updated);
      appendReply({ id: replyId, role: "assistant", content: reply, citations });
    } catch (e) {
      onError?.(e.message);
      appendReply({ role: "assistant", content: `⚠️ Error: ${e.message}` });
    } finally {
      setStreaming(false);
      setLoading(false);
    }
  }

  function saveResponse(content, toolId) {
    const entry = {
      id: crypto.randomUUID(),
      tool: toolId,
      toolLabel: TOOLS.find((t) => t.id === toolId)?.label,
      content,
      savedAt: new Date().toLocaleString(),
      title: content.slice(0, 60).replace(/\n/g, " ") + "…",
    };
    setSavedResponses((p) => [entry, ...p]);
    return entry;
  }

  function deleteSaved(id) {
    setSavedResponses((p) => p.filter((r) => r.id !== id));
  }

  function clearActiveConversation() {
    setConversations((p) => ({ ...p, [activeTool]: [] }));
  }

  return {
    conversations,
    currentConvo,
    savedResponses,
    input,
    loading,
    streaming,
    setInput,
    setConversations,
    sendMessage,
    saveResponse,
    deleteSaved,
    clearActiveConversation,
    bottomRef,
  };
}
