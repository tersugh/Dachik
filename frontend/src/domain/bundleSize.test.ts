import { describe, expect, it } from "vitest";

import { bundleSizeToBytes, formatBundleSize, formatObservedBytes } from "./bundleSize";

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

describe("observed byte display", () => {
  it("uses integer arithmetic and limited precision", () => {
    expect(formatObservedBytes(2_450_000_000)).toBe("2.45 GB");
    expect(formatObservedBytes(27_550_000)).toBe("27.6 MB");
    expect(formatObservedBytes(0)).toBe("0 bytes");
    expect(formatObservedBytes(29_999_784_800)).toBe("30 GB");
    expect(formatObservedBytes(23_909_784_800)).toBe("23.91 GB");
    expect(formatObservedBytes(215_200)).toBe("215.2 KB");
  });
});
