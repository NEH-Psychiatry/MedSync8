import { useState } from "react";
import { TOOLS, TOOL_COLORS, QUICK_PROMPTS } from "./prompts";
import { exportToPDF } from "./lib/pdf";
import Spinner from "./components/Spinner";
import MessageBubble from "./components/MessageBubble";
import TemplatesPanel from "./components/TemplatesPanel";
import SavedResponsesPanel from "./components/SavedResponsesPanel";
import ChatInput from "./components/ChatInput";
import { useChat } from "./hooks/useChat";

export default function PsychiatryWorkbench() {
  const [activeTool, setActiveTool] = useState("policy");
  const [activePanel, setActivePanel] = useState("chat");
  const [toast, setToast] = useState(null);
  const [templateFilter, setTemplateFilter] = useState("all");

  const {
    conversations,
    currentConvo,
    savedResponses,
    input,
    loading,
    setInput,
    sendMessage,
    saveResponse,
    deleteSaved,
    clearActiveConversation,
    bottomRef,
  } = useChat({ activeTool });

  const tool = TOOLS.find((t) => t.id === activeTool);

  function showToast(msg, color = "#5B9BD5") {
    setToast({ msg, color });
    setTimeout(() => setToast(null), 2500);
  }

  function handleSaveResponse(content, toolId) {
    saveResponse(content, toolId);
    showToast("✓ Response saved", "#5BC98A");
  }

  function handleDeleteSaved(id) {
    deleteSaved(id);
    showToast("Deleted", "#E08A8A");
  }

  function handleCopySaved(content) {
    navigator.clipboard.writeText(content);
    showToast("Copied!");
  }

  return (
    <div style={{
      height: "100vh", display: "flex", flexDirection: "column",
      background: "linear-gradient(160deg, #080F18 0%, #0E1C2D 60%, #0A1520 100%)",
      color: "#C8DCF0", fontFamily: "Georgia, serif", overflow: "hidden",
    }}>
      <style>{`
        @keyframes fadeIn { from { opacity:0; transform:translateY(6px) } to { opacity:1; transform:translateY(0) } }
        @keyframes spin { to { transform:rotate(360deg) } }
        @keyframes toastIn { from { opacity:0; transform:translateY(20px) } to { opacity:1; transform:translateY(0) } }
        ::-webkit-scrollbar { width:5px } ::-webkit-scrollbar-thumb { background:rgba(91,155,213,0.25); border-radius:3px }
        .tab-btn:hover { background: rgba(255,255,255,0.06) !important; }
        .panel-btn:hover { opacity: 0.85; }
        .qbtn:hover { background: rgba(44,95,138,0.25) !important; border-color: rgba(91,155,213,0.4) !important; }
        .tbtn:hover { background: rgba(44,95,138,0.2) !important; }
        .send:hover:not(:disabled) { filter: brightness(1.15); transform: translateY(-1px); }
        textarea { caret-color: #5B9BD5; }
        textarea:focus { outline: none !important; }
        .saved-card:hover { background: rgba(255,255,255,0.05) !important; }
      `}</style>

      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 20px", borderBottom: "1px solid rgba(255,255,255,0.05)",
        background: "rgba(8,15,24,0.8)", backdropFilter: "blur(16px)", flexShrink: 0,
        flexWrap: "wrap", gap: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "linear-gradient(135deg, #1E4D73, #0A2A40)",
            border: "1px solid rgba(91,155,213,0.35)",
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18,
          }}>{"⚕"}</div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#EAF2FB", letterSpacing: "-0.2px" }}>
              Psychiatry AI Workbench
            </div>
            <div style={{ fontSize: 11, color: "#3D6080", fontFamily: "system-ui", marginTop: 1 }}>
              Nuestra Esperanza Health &middot; AI-assisted clinical tools
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="panel-btn" onClick={() => setActivePanel((p) => (p === "saved" ? "chat" : "saved"))} style={{
            padding: "6px 12px", borderRadius: 8,
            background: activePanel === "saved" ? "rgba(91,155,213,0.2)" : "rgba(255,255,255,0.05)",
            border: `1px solid ${activePanel === "saved" ? "rgba(91,155,213,0.4)" : "rgba(255,255,255,0.07)"}`,
            color: activePanel === "saved" ? "#9DCAF0" : "#5B7A96",
            fontSize: 12, cursor: "pointer", fontFamily: "system-ui", transition: "all 0.2s",
          }}>{"💾"} {savedResponses.length} Saved</button>
        </div>
      </div>

      <div style={{
        display: "flex", padding: "8px 16px 0", gap: 4,
        background: "rgba(8,15,24,0.6)", flexShrink: 0, overflowX: "auto",
      }}>
        {TOOLS.map((t) => {
          const active = activeTool === t.id;
          const color = TOOL_COLORS[t.id];
          return (
            <button key={t.id} className="tab-btn" onClick={() => { setActiveTool(t.id); setActivePanel("chat"); }} style={{
              padding: "8px 16px", borderRadius: "8px 8px 0 0",
              border: "1px solid transparent",
              borderBottom: active ? `2px solid ${color}` : "2px solid transparent",
              background: active ? `${color}22` : "transparent",
              color: active ? "#EAF2FB" : "#3D6080",
              cursor: "pointer", fontSize: 13, fontFamily: "system-ui", fontWeight: active ? 600 : 400,
              display: "flex", alignItems: "center", gap: 6, transition: "all 0.2s", whiteSpace: "nowrap",
            }}>
              {t.icon} {t.label}
              {conversations[t.id].length > 0 && (
                <span style={{ background: `${color}22`, color, borderRadius: 20, padding: "0 6px", fontSize: 10 }}>
                  {Math.ceil(conversations[t.id].length / 2)}
                </span>
              )}
            </button>
          );
        })}
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          <button className="tab-btn" onClick={() => setActivePanel((p) => (p === "templates" ? "chat" : "templates"))} style={{
            padding: "8px 14px", borderRadius: "8px 8px 0 0",
            border: "1px solid transparent",
            borderBottom: activePanel === "templates" ? "2px solid #E8AA5A" : "2px solid transparent",
            background: activePanel === "templates" ? "rgba(130,90,30,0.2)" : "transparent",
            color: activePanel === "templates" ? "#EAF2FB" : "#3D6080",
            cursor: "pointer", fontSize: 12, fontFamily: "system-ui", transition: "all 0.2s",
          }}>{"📚"} Templates</button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", padding: "0 16px 16px" }}>
        {activePanel === "templates" && (
          <TemplatesPanel
            templateFilter={templateFilter}
            setTemplateFilter={setTemplateFilter}
            onTemplateClick={(tmpl) => {
              setActiveTool(tmpl.category);
              setActivePanel("chat");
              sendMessage(tmpl.prompt);
            }}
          />
        )}

        {activePanel === "saved" && (
          <SavedResponsesPanel
            savedResponses={savedResponses}
            onExport={(r) => exportToPDF(r.title, r.content)}
            onCopy={handleCopySaved}
            onDelete={handleDeleteSaved}
          />
        )}

        {activePanel === "chat" && (
          <>
            <div style={{ flex: 1, overflow: "auto", paddingTop: 16, paddingBottom: 4 }}>
              {currentConvo.length === 0 ? (
                <div style={{ animation: "fadeIn 0.4s" }}>
                  <div style={{ fontSize: 12, color: "#2E4A60", fontFamily: "system-ui", marginBottom: 12 }}>
                    Quick prompts for {tool.label}:
                  </div>
                  {QUICK_PROMPTS[activeTool].map((p, i) => (
                    <button key={i} className="qbtn" onClick={() => sendMessage(p)} style={{
                      display: "block", width: "100%", textAlign: "left",
                      padding: "10px 14px", marginBottom: 8,
                      background: "rgba(14,28,45,0.6)", border: "1px solid rgba(91,155,213,0.12)",
                      borderRadius: 10, color: "#7AB8D8", cursor: "pointer",
                      fontSize: 13, fontFamily: "Georgia,serif", lineHeight: 1.5, transition: "all 0.2s",
                    }}>
                      <span style={{ color: TOOL_COLORS[activeTool], marginRight: 8 }}>{"→"}</span>{p}
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  {currentConvo.map((msg, i) => (
                    <MessageBubble
                      key={i}
                      {...msg}
                      onSave={() => handleSaveResponse(msg.content, activeTool)}
                      onExport={() => exportToPDF(`${tool.label} — ${new Date().toLocaleDateString()}`, msg.content)}
                    />
                  ))}
                  {loading && <Spinner />}
                  <div ref={bottomRef} style={{ height: 40 }} />
                </>
              )}
            </div>

            <ChatInput
              input={input}
              setInput={setInput}
              onSend={sendMessage}
              loading={loading}
              placeholder={`${tool.icon} ${tool.desc} — describe what you need…`}
              showClear={currentConvo.length > 0}
              onClear={clearActiveConversation}
              sendColor={TOOL_COLORS[activeTool]}
            />
          </>
        )}
      </div>

      {toast && (
        <div style={{
          position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: "rgba(14,28,45,0.97)", border: `1px solid ${toast.color}44`,
          borderRadius: 10, padding: "10px 20px", color: toast.color,
          fontFamily: "system-ui", fontSize: 13, zIndex: 1000,
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)", animation: "toastIn 0.25s ease",
          backdropFilter: "blur(16px)",
        }}>{toast.msg}</div>
      )}
    </div>
  );
}
