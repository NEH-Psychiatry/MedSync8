import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

function mockResponse(ok, payload, status = 200) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(payload),
  };
}

describe("PsychiatryWorkbench", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    globalThis.fetch = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn() },
    });
  });

  it("sends a message and renders assistant reply", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      mockResponse(true, { reply: "Assistant reply", citations: [], model: "test" }),
    );

    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByPlaceholderText(/Policies & procedures/i);
    await user.type(input, "Hello backend");
    await user.click(screen.getByRole("button", { name: "↑" }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    const requestBody = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(requestBody.tool).toBe("policy");
    expect(requestBody.messages.at(-1).content).toBe("Hello backend");

    expect(await screen.findByText("Assistant reply")).toBeInTheDocument();
  });

  it("renders backend errors in chat", async () => {
    globalThis.fetch.mockResolvedValueOnce(mockResponse(false, { detail: "backend exploded" }, 500));

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByPlaceholderText(/Policies & procedures/i), "trigger error");
    await user.click(screen.getByRole("button", { name: "↑" }));

    expect(await screen.findByText("⚠️ Error: backend exploded")).toBeInTheDocument();
  });

  it("renders citations returned by backend", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      mockResponse(true, {
        reply: "Cited answer",
        citations: [{ index: 1, doc_id: "policy.md", chunk_id: 2, score: 0.91 }],
        model: "test",
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByPlaceholderText(/Policies & procedures/i), "Need citation");
    await user.click(screen.getByRole("button", { name: "↑" }));

    expect(await screen.findByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("policy.md")).toBeInTheDocument();
    expect(screen.getByText(/chunk 2/i)).toBeInTheDocument();
  });

  it("loads saved responses persisted in localStorage", async () => {
    localStorage.setItem("saved_responses", JSON.stringify([{
      id: 1,
      tool: "policy",
      toolLabel: "Policy",
      content: "Persisted saved response body",
      savedAt: "now",
      title: "Persisted saved response…",
    }]));

    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Saved/i }));

    expect(screen.getByText("Persisted saved response…")).toBeInTheDocument();
    expect(screen.getByText(/Persisted saved response body/i)).toBeInTheDocument();
  });

  it("uses template click to send template prompt", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      mockResponse(true, { reply: "Template response", citations: [], model: "test" }),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: /Templates/i }));
    await user.click(screen.getByText("Telepsychiatry CS Policy Shell"));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    const body = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(body.tool).toBe("policy");
    expect(body.messages[0].content).toMatch(/telepsychiatry controlled substance prescribing policy shell/i);
  });
});
