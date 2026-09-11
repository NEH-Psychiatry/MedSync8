import { useEffect, useRef, useState } from "react";
import { TOOLS } from "../prompts";
import { callBackend } from "../lib/api";

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
  const bottomRef = useRef(null);

  const currentConvo = conversations[activeTool];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversations, loading]);

  useEffect(() => {
    localStorage.setItem("saved_responses", JSON.stringify(savedResponses));
  }, [savedResponses]);

  async function sendMessage(text) {
    if (!text.trim() || loading) return;

    const userMsg = { role: "user", content: text };
    const updated = [...currentConvo, userMsg];
    setConversations((p) => ({ ...p, [activeTool]: updated }));
    setInput("");
    setLoading(true);

    try {
      const { reply, citations } = await callBackend(activeTool, updated);
      setConversations((p) => ({
        ...p,
        [activeTool]: [...updated, { role: "assistant", content: reply, citations }],
      }));
    } catch (e) {
      onError?.(e.message);
      setConversations((p) => ({
        ...p,
        [activeTool]: [...updated, { role: "assistant", content: `⚠️ Error: ${e.message}` }],
      }));
    } finally {
      setLoading(false);
    }
  }

  function saveResponse(content, toolId) {
    const entry = {
      id: Date.now(),
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
    setInput,
    setConversations,
    sendMessage,
    saveResponse,
    deleteSaved,
    clearActiveConversation,
    bottomRef,
  };
}
