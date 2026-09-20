import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("sends a cross-category template under the template's own tool", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      mockResponse(true, { reply: "Lecture outline", citations: [], model: "test" }),
    );

    const user = userEvent.setup();
    render(<App />);

    // Active tool starts as "policy"; the template belongs to "lecture".
    await user.click(screen.getByRole("button", { name: /Templates/i }));
    await user.click(screen.getByText("Adult ADHD Lecture (60 min)"));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    const body = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(body.tool).toBe("lecture");
    expect(await screen.findByText("Lecture outline")).toBeInTheDocument();
  });

  it("does not resurrect a conversation cleared while a reply is in flight", async () => {
    let resolveFetch;
    globalThis.fetch.mockReturnValueOnce(new Promise((res) => { resolveFetch = res; }));

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByPlaceholderText(/Policies & procedures/i), "in-flight message");
    await user.click(screen.getByRole("button", { name: "↑" }));
    expect(await screen.findByText("in-flight message")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("in-flight message")).not.toBeInTheDocument();

    resolveFetch(mockResponse(true, { reply: "late reply", citations: [], model: "test" }));
    // Back on the empty-conversation view; the late reply must not reappear.
    await waitFor(() => expect(screen.getByText(/Quick prompts/i)).toBeInTheDocument());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("late reply")).not.toBeInTheDocument();
    expect(screen.queryByText("in-flight message")).not.toBeInTheDocument();
  });

  it("assigns unique ids to responses saved in quick succession", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      mockResponse(true, { reply: "Save me twice", citations: [], model: "test" }),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByPlaceholderText(/Policies & procedures/i), "hello");
    await user.click(screen.getByRole("button", { name: "↑" }));
    await screen.findByText("Save me twice");

    await user.hover(screen.getByText("Save me twice"));
    // fireEvent, not user.click: user-event's pointer simulation does not
    // reach the hover-revealed absolutely-positioned action button in jsdom.
    const saveButton = await screen.findByRole("button", { name: "💾 Save" });
    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem("saved_responses"));
      expect(saved).toHaveLength(2);
      expect(saved[0].id).not.toBe(saved[1].id);
    });
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
