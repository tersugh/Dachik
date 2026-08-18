import { describe, expect, it } from "vitest";

import { formatAuditTime, formatAuditTimestamp } from "./dateTime";

describe("audit timestamp presentation", () => {
  const raw = "2026-08-18T19:54:41.725503+00:00";

  it("formats exact evidence time in the audit timezone without changing the source", () => {
    expect(formatAuditTimestamp(raw, "Africa/Lagos", { includeSeconds: true })).toBe(
      "18 Aug 2026 · 20:54:41",
    );
    expect(raw).toBe("2026-08-18T19:54:41.725503+00:00");
  });

  it("supports non-Nigerian timezones", () => {
    expect(formatAuditTimestamp(raw, "America/New_York", { includeSeconds: true })).toBe(
      "18 Aug 2026 · 15:54:41",
    );
  });

  it("uses the same timezone for hourly and exact timestamps", () => {
    expect(formatAuditTime(raw, "Africa/Lagos")).toBe("20:54");
    expect(formatAuditTimestamp(raw, "Africa/Lagos")).toBe("18 Aug 2026 · 20:54");
  });
});
