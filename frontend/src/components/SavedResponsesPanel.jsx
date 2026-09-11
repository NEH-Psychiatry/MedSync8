import { TOOLS, TOOL_COLORS } from "../prompts";

export default function SavedResponsesPanel({ savedResponses, onExport, onCopy, onDelete }) {
  if (savedResponses.length === 0) {
    return (
      <div style={{ flex: 1, overflow: "auto", paddingTop: 16, animation: "fadeIn 0.3s" }}>
        <div style={{ textAlign: "center", padding: 48, color: "#2E4A60" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>{"💾"}</div>
          <div style={{ fontFamily: "system-ui", fontSize: 14 }}>No saved responses yet.</div>
          <div style={{ fontFamily: "system-ui", fontSize: 12, marginTop: 6 }}>Hover over any AI response to save it.</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: "auto", paddingTop: 16, animation: "fadeIn 0.3s" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {savedResponses.map((r) => (
          <div key={r.id} className="saved-card" style={{
            background: "rgba(14,28,45,0.7)", border: "1px solid rgba(255,255,255,0.07)",
            borderRadius: 12, padding: 16, transition: "all 0.2s",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
              <div>
                <span style={{
                  fontSize: 10, color: TOOL_COLORS[r.tool], fontFamily: "system-ui",
                  textTransform: "uppercase", letterSpacing: 1, marginRight: 8,
                }}>{TOOLS.find((t) => t.id === r.tool)?.icon} {r.toolLabel}</span>
                <span style={{ fontSize: 11, color: "#2E4A60", fontFamily: "system-ui" }}>{r.savedAt}</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => onExport(r)} style={{
                  padding: "3px 10px", borderRadius: 6, background: "rgba(44,95,138,0.2)",
                  border: "1px solid rgba(91,155,213,0.3)", color: "#7AB8D8",
                  fontSize: 11, cursor: "pointer", fontFamily: "system-ui",
                }}>{"🖨"} PDF</button>
                <button onClick={() => onCopy(r.content)} style={{
                  padding: "3px 10px", borderRadius: 6, background: "rgba(44,95,138,0.2)",
                  border: "1px solid rgba(91,155,213,0.3)", color: "#7AB8D8",
                  fontSize: 11, cursor: "pointer", fontFamily: "system-ui",
                }}>{"📋"} Copy</button>
                <button onClick={() => onDelete(r.id)} style={{
                  padding: "3px 10px", borderRadius: 6, background: "rgba(138,44,44,0.15)",
                  border: "1px solid rgba(213,91,91,0.2)", color: "#C08080",
                  fontSize: 11, cursor: "pointer", fontFamily: "system-ui",
                }}>{"✕"}</button>
              </div>
            </div>
            <div style={{ fontSize: 13, color: "#7A9DB8", fontFamily: "system-ui", marginBottom: 8 }}>{r.title}</div>
            <div style={{
              maxHeight: 120, overflow: "hidden", position: "relative",
              fontSize: 13, color: "#4A6880", lineHeight: 1.7, fontFamily: "Georgia,serif",
            }}>
              {r.content.slice(0, 300)}{"…"}
              <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 40, background: "linear-gradient(transparent, rgba(14,28,45,0.95))" }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
