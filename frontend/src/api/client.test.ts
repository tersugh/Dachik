import { afterEach, describe, expect, it, vi } from "vitest";

import { assertSafeAutomatedTestApiUrl, dachikApi } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("Dachik API response validation", () => {
  it("refuses the normal development API in automated test mode", () => {
    expect(() => assertSafeAutomatedTestApiUrl("http://127.0.0.1:8765", "test")).toThrow(
      "must not target the normal Dachik development API",
    );
  });

  it("rejects a null device-list response instead of crashing React", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(null) } as unknown as Response),
    );

    await expect(dachikApi.listDevices()).rejects.toThrow(
      "Invalid devices response from Dachik service",
    );
  });
});
