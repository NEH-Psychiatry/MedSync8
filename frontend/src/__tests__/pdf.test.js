import { afterEach, describe, expect, it, vi } from "vitest";

import { escapeHtml, exportToPDF } from "../lib/pdf";

describe("escapeHtml", () => {
  it("escapes ampersands and angle brackets", () => {
    expect(escapeHtml('<b>&"</b>')).toBe('&lt;b&gt;&amp;"&lt;/b&gt;');
  });
});

describe("exportToPDF", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("escapes HTML in both the title and the content", () => {
    const write = vi.fn();
    vi.spyOn(window, "open").mockReturnValue({
      document: { write, close: vi.fn() },
      print: vi.fn(),
    });

    exportToPDF("<img src=x onerror=alert(1)>", "body & <script>bad()</script>");

    const html = write.mock.calls[0][0];
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).toContain("body &amp; &lt;script&gt;bad()&lt;/script&gt;");
  });

  it("does nothing when the popup is blocked", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(() => exportToPDF("t", "c")).not.toThrow();
  });
});
