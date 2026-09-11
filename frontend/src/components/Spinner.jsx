export default function Spinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 0", animation: "fadeIn 0.3s" }}>
      <div style={{
        width: 18, height: 18, borderRadius: "50%",
        border: "2px solid rgba(91,155,213,0.2)", borderTopColor: "#5B9BD5",
        animation: "spin 0.8s linear infinite",
      }} />
      <span style={{ color: "#5B7A96", fontStyle: "italic", fontSize: 13, fontFamily: "Georgia,serif" }}>
        Generating response...
      </span>
    </div>
  );
}
