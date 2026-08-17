import { describe, expect, it } from "vitest";

import { bundleSizeToBytes, formatBundleSize } from "./bundleSize";

describe("bundleSizeToBytes", () => {
  it("converts decimal MB to integer bytes", () => {
    expect(bundleSizeToBytes("30", "MB")).toBe(30_000_000);
  });

  it("converts decimal GB to integer bytes", () => {
    expect(bundleSizeToBytes("30", "GB")).toBe(30_000_000_000);
  });

  it("converts fractional decimal GB without floating-point arithmetic", () => {
    expect(bundleSizeToBytes("30.5", "GB")).toBe(30_500_000_000);
    expect(formatBundleSize(30_500_000_000)).toBe("30.5 GB");
  });

  it.each(["", "0", "-1", "not-a-number"])("rejects invalid value %s", (value) => {
    expect(() => bundleSizeToBytes(value, "GB")).toThrow();
  });
});
