import { useState } from "react";
import Citations from "./Citations";

export default function MessageBubble({ role, content, citations, onSave, onExport }) {
  const isUser = role === "user";
  const [hover, setHover] = useState(false);

  return (
    <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", marginBottom: 18, animation: "fadeIn 0.35s ease" }}>
      {!isUser && (
        <div style={{
          width: 30, height: 30, borderRadius: "50%", flexShrink: 0,
          background: "linear-gradient(135deg, #1E4D73, #0D2D47)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 13, marginRight: 10, marginTop: 4,
          border: "1px solid rgba(91,155,213,0.3)", boxShadow: "0 2px 10px rgba(0,0,0,0.3)",
        }}>{"⚕️"}</div>
      )}
      <div onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} style={{ maxWidth: "80%", position: "relative" }}>
        <div style={{
          background: isUser ? "linear-gradient(135deg, #2C5F8A, #1A3D5C)" : "rgba(20,35,52,0.8)",
          border: isUser ? "none" : "1px solid rgba(91,155,213,0.15)",
          borderRadius: isUser ? "16px 16px 3px 16px" : "3px 16px 16px 16px",
          padding: "11px 15px", color: isUser ? "#EAF2FB" : "#C8DCF0",
          fontSize: 13.5, lineHeight: 1.75, fontFamily: "Georgia,serif", whiteSpace: "pre-wrap",
          boxShadow: isUser ? "0 4px 20px rgba(44,95,138,0.3)" : "0 2px 12px rgba(0,0,0,0.2)",
        }}>
          {content}
          {!isUser && <Citations citations={citations} />}
        </div>
        {!isUser && hover && (
          <div style={{ position: "absolute", bottom: -30, left: 0, display: "flex", gap: 6, zIndex: 10, animation: "fadeIn 0.15s" }}>
            {[["💾 Save", onSave], ["🖨 Export PDF", onExport]].map(([label, fn]) => (
              <button key={label} onClick={fn} style={{
                padding: "3px 10px", borderRadius: 20,
                background: "rgba(20,35,52,0.95)", border: "1px solid rgba(91,155,213,0.3)",
                color: "#7AB8D8", fontSize: 11, cursor: "pointer", fontFamily: "system-ui",
                backdropFilter: "blur(8px)",
              }}>{label}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
