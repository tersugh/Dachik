interface LocalDateTimeParts {
  day: string;
  month: string;
  year: string;
  hour: string;
  minute: string;
  second: string;
}

function localParts(value: string, timezone: string): LocalDateTimeParts {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new Error("Invalid audit timestamp");
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const valueFor = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return {
    day: valueFor("day"),
    month: valueFor("month"),
    year: valueFor("year"),
    hour: valueFor("hour"),
    minute: valueFor("minute"),
    second: valueFor("second"),
  };
}

export function formatAuditTimestamp(
  value: string,
  timezone: string,
  options: { includeSeconds?: boolean } = {},
): string {
  const parts = localParts(value, timezone);
  const seconds = options.includeSeconds ? `:${parts.second}` : "";
  return `${parts.day} ${parts.month} ${parts.year} · ${parts.hour}:${parts.minute}${seconds}`;
}

export function formatAuditDay(value: string, timezone: string): string {
  const parts = localParts(value, timezone);
  return `${parts.day} ${parts.month} ${parts.year}`;
}

export function formatAuditTime(value: string, timezone: string): string {
  const parts = localParts(value, timezone);
  return `${parts.hour}:${parts.minute}`;
}
