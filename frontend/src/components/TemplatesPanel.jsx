import { TEMPLATE_LIBRARY, TOOLS, TOOL_COLORS } from "../prompts";

export default function TemplatesPanel({ templateFilter, setTemplateFilter, onTemplateClick }) {
  const filteredTemplates = templateFilter === "all"
    ? TEMPLATE_LIBRARY
    : TEMPLATE_LIBRARY.filter((t) => t.category === templateFilter);

  return (
    <div style={{ flex: 1, overflow: "auto", paddingTop: 16, animation: "fadeIn 0.3s" }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {["all", "policy", "supervision", "lecture", "chat"].map((f) => (
          <button key={f} onClick={() => setTemplateFilter(f)} className="tbtn" style={{
            padding: "5px 14px", borderRadius: 20,
            background: templateFilter === f ? "rgba(44,95,138,0.35)" : "rgba(255,255,255,0.04)",
            border: `1px solid ${templateFilter === f ? "rgba(91,155,213,0.5)" : "rgba(255,255,255,0.07)"}`,
            color: templateFilter === f ? "#9DCAF0" : "#5B7A96",
            fontSize: 12, cursor: "pointer", fontFamily: "system-ui", transition: "all 0.2s",
            textTransform: "capitalize",
          }}>{f}</button>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
        {filteredTemplates.map((tmpl) => {
          const color = TOOL_COLORS[tmpl.category];
          return (
            <div key={tmpl.id} style={{
              background: "rgba(14,28,45,0.7)", border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: 12, padding: 16, cursor: "pointer", transition: "all 0.2s", animation: "fadeIn 0.3s",
            }}
              onClick={() => onTemplateClick(tmpl)}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = `${color}44`; e.currentTarget.style.background = "rgba(20,38,58,0.9)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)"; e.currentTarget.style.background = "rgba(14,28,45,0.7)"; }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 10, color, fontFamily: "system-ui", textTransform: "uppercase", letterSpacing: 1 }}>
                  {TOOLS.find((t) => t.id === tmpl.category)?.icon} {tmpl.category}
                </span>
              </div>
              <div style={{ fontSize: 14, color: "#C8DCF0", fontWeight: 600, marginBottom: 6 }}>{tmpl.label}</div>
              <div style={{ fontSize: 12, color: "#4A6880", lineHeight: 1.6, fontFamily: "system-ui" }}>
                {tmpl.prompt.slice(0, 90)}{"…"}
              </div>
              <div style={{
                marginTop: 12, padding: "5px 12px", borderRadius: 6, display: "inline-block",
                background: `${color}18`, border: `1px solid ${color}33`, color, fontSize: 11, fontFamily: "system-ui",
              }}>Use template {"→"}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
