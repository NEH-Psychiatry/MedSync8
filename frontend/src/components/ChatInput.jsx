export default function ChatInput({
  input,
  setInput,
  onSend,
  loading,
  placeholder,
  showClear,
  onClear,
  sendColor,
}) {
  return (
    <>
      <div style={{
        flexShrink: 0,
        background: "rgba(14,28,45,0.85)", border: "1px solid rgba(91,155,213,0.15)",
        borderRadius: 14, padding: "10px 12px", display: "flex", gap: 8, alignItems: "flex-end",
        backdropFilter: "blur(12px)",
      }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(input); } }}
          placeholder={placeholder}
          rows={2}
          style={{
            flex: 1, background: "transparent", border: "none",
            color: "#C8DCF0", fontFamily: "Georgia,serif", fontSize: 14,
            lineHeight: 1.6, resize: "none",
          }}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {showClear && (
            <button onClick={onClear} style={{
              padding: "4px 8px", borderRadius: 6, background: "transparent",
              border: "1px solid rgba(255,255,255,0.06)", color: "#2E4A60",
              fontSize: 11, cursor: "pointer", fontFamily: "system-ui",
            }}>Clear</button>
          )}
          <button className="send" onClick={() => onSend(input)} disabled={loading || !input.trim()} style={{
            padding: "9px 16px", borderRadius: 10, fontSize: 18,
            background: !input.trim() || loading
              ? "rgba(44,95,138,0.15)"
              : `linear-gradient(135deg, ${sendColor}, #1A3D5C)`,
            border: "none",
            color: !input.trim() || loading ? "#2E4A60" : "#EAF2FB",
            cursor: !input.trim() || loading ? "not-allowed" : "pointer",
            transition: "all 0.2s",
            boxShadow: !input.trim() || loading ? "none" : "0 4px 16px rgba(44,95,138,0.35)",
          }}>{"↑"}</button>
        </div>
      </div>
      <div style={{ textAlign: "center", fontSize: 10, color: "#1E3348", fontFamily: "system-ui", marginTop: 6 }}>
        Enter to send &middot; Shift+Enter for new line &middot; AI-generated &mdash; apply clinical judgment before use
      </div>
    </>
  );
}
