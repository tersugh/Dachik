export type BundleUnit = "MB" | "GB";

const UNIT_BYTES: Record<BundleUnit, bigint> = {
  MB: 1_000_000n,
  GB: 1_000_000_000n,
};

export function bundleSizeToBytes(input: string, unit: BundleUnit): number {
  const value = input.trim();
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) {
    throw new Error("Bundle size must be a positive number");
  }

  const whole = match[1];
  const fraction = match[2] ?? "";
  if (!whole) {
    throw new Error("Bundle size must be a positive number");
  }

  const scale = 10n ** BigInt(fraction.length);
  const decimalInteger = BigInt(`${whole}${fraction}`);
  const numerator = decimalInteger * UNIT_BYTES[unit];
  if (decimalInteger <= 0n) {
    throw new Error("Bundle size must be greater than zero");
  }
  if (numerator % scale !== 0n) {
    throw new Error("Bundle size is more precise than one byte");
  }

  const bytes = numerator / scale;
  if (bytes > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("Bundle size is too large");
  }
  return Number(bytes);
}

export function formatBundleSize(bytes: number): string {
  if (!Number.isSafeInteger(bytes) || bytes <= 0) return "Invalid bundle size";
  const byteValue = BigInt(bytes);
  const unit: BundleUnit = byteValue >= UNIT_BYTES.GB ? "GB" : "MB";
  const unitBytes = UNIT_BYTES[unit];
  const whole = byteValue / unitBytes;
  const remainder = byteValue % unitBytes;
  if (remainder === 0n) return `${whole} ${unit}`;

  const digits = unit === "GB" ? 9 : 6;
  const fraction = remainder.toString().padStart(digits, "0").replace(/0+$/, "");
  return `${whole}.${fraction} ${unit}`;
}

export function formatObservedBytes(bytes: number): string {
  if (!Number.isSafeInteger(bytes) || bytes < 0) return "Unknown";
  const value = BigInt(bytes);
  const units = [
    ["GB", 1_000_000_000n],
    ["MB", 1_000_000n],
    ["KB", 1_000n],
  ] as const;
  const [label, divisor] = units.find(([, size]) => value >= size) ?? ["bytes", 1n];
  const decimalPlaces = label === "GB" ? 2 : label === "bytes" ? 0 : 1;
  const scale = 10n ** BigInt(decimalPlaces);
  const rounded = (value * scale + divisor / 2n) / divisor;
  const whole = rounded / scale;
  const fraction = (rounded % scale).toString().padStart(decimalPlaces, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction} ${label}` : `${whole} ${label}`;
}
