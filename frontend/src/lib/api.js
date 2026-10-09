const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export function assertProductionApiBase(apiBase, isProduction) {
  if (!isProduction) return;

  let hostname;
  try {
    hostname = new URL(apiBase).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    hostname = "";
  }
  const isLocalhost =
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "[::1]" ||
    hostname.startsWith("127.");

  if (
    typeof apiBase !== "string" ||
    !apiBase.startsWith("https://") ||
    !hostname ||
    isLocalhost
  ) {
    throw new Error("VITE_API_BASE must be an explicit https:// production URL");
  }
}

export async function callBackend(tool, messages) {
  assertProductionApiBase(API_BASE, import.meta.env.PROD);

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
