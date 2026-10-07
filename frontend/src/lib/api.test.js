import { describe, expect, it } from "vitest";

import { assertProductionApiBase } from "./api";

describe("assertProductionApiBase", () => {
  it("allows the local HTTP fallback outside production", () => {
    expect(() => assertProductionApiBase("http://localhost:8000", false)).not.toThrow();
  });

  it("rejects missing, non-HTTPS, and loopback production API bases", () => {
    expect(() => assertProductionApiBase(undefined, true)).toThrow(
      /https:\/\/ production URL/,
    );
    expect(() => assertProductionApiBase("http://localhost:8000", true)).toThrow(
      /https:\/\/ production URL/,
    );
    expect(() => assertProductionApiBase("https://localhost:8000", true)).toThrow(
      /https:\/\/ production URL/,
    );
    expect(() => assertProductionApiBase("https://127.0.0.2:8443", true)).toThrow(
      /https:\/\/ production URL/,
    );
    expect(() => assertProductionApiBase("https://[::1]:8443", true)).toThrow(
      /https:\/\/ production URL/,
    );
  });

  it("accepts an HTTPS production API base", () => {
    expect(() =>
      assertProductionApiBase("https://api.example.test", true),
    ).not.toThrow();
  });
});
