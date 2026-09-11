export default function Citations({ citations }) {
  if (!citations?.length) return null;
  return (
    <div style={{
      marginTop: 10, paddingTop: 8, borderTop: "1px solid rgba(91,155,213,0.15)",
      fontFamily: "system-ui", fontSize: 11, color: "#5B7A96",
    }}>
      <div style={{ marginBottom: 4, color: "#3D6080", letterSpacing: 0.4, textTransform: "uppercase" }}>
        Sources
      </div>
      {citations.map((c) => (
        <div key={c.index} style={{ marginBottom: 2 }}>
          <span style={{ color: "#9DCAF0" }}>[{c.index}]</span>{" "}
          <span style={{ fontFamily: "monospace" }}>{c.doc_id}</span>
          <span style={{ color: "#3D6080" }}> · chunk {c.chunk_id} · {(c.score * 100).toFixed(0)}% match</span>
        </div>
      ))}
    </div>
  );
}
