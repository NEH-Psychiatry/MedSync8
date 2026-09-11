const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function callBackend(tool, messages) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, messages, use_rag: true }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail ?? `Backend request failed (${res.status})`);
  }

  return res.json();
}
