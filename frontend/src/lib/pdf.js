export function exportToPDF(title, content) {
  const escaped = content.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const win = window.open("", "_blank");
  if (!win) return;
  win.document.write(`<!DOCTYPE html><html><head>
    <title>${title}</title>
    <style>
      body { font-family: Georgia, serif; max-width: 820px; margin: 40px auto; padding: 0 32px; color: #1a1a2e; line-height: 1.8; }
      h1 { font-size: 22px; border-bottom: 2px solid #2C5F8A; padding-bottom: 10px; color: #1A3D5C; }
      .meta { font-size: 12px; color: #666; margin-bottom: 24px; font-family: system-ui; }
      pre { white-space: pre-wrap; font-family: Georgia, serif; font-size: 14px; }
      @media print { body { margin: 20px; } }
    </style>
    </head><body>
    <h1>${title}</h1>
    <div class="meta">Generated: ${new Date().toLocaleDateString()} &middot; Nuestra Esperanza Health &middot; AI-assisted draft &mdash; clinical review required</div>
    <pre>${escaped}</pre>
    </body></html>`);
  win.document.close();
  setTimeout(() => win.print(), 500);
}
