export interface HealthResponse {
  status: "ok";
  service: "dachik";
  version: string;
}

export interface Device {
  id: string;
  hostname: string;
  display_name: string;
  operating_system: string;
  operating_system_version: string | null;
  created_at: string;
  updated_at: string;
}

export interface DataBundle {
  id: string;
  provider_name: string;
  plan_name: string;
  allowance_bytes: number;
  billing_cycle_start: string;
  billing_cycle_end: string;
  timezone: string;
  created_at: string;
}

export interface Experiment {
  id: string;
  data_bundle_id: string;
  device_id: string;
  measurement_source_id: string | null;
  measurement_boundary: string;
  methodology_version: string;
  user_notes: string | null;
  started_at: string | null;
  ended_at: string | null;
  status: "draft" | "active" | "completed" | "cancelled";
  created_at: string;
}

export interface ISPBalanceSnapshot {
  id: string;
  experiment_id: string;
  timestamp_utc: string;
  reported_value: string;
  reported_unit: string;
  snapshot_type: "remaining_balance" | "cumulative_consumption";
  normalized_bytes: number | null;
  provenance: "manual";
  note: string | null;
  correction_of_snapshot_id: string | null;
  created_at: string;
}

export interface CurrentExperimentUsage {
  experiment_id: string | null;
  status: "no_active_plan" | "multiple_active_plans" | "waiting" | "active" | "paused" | "interrupted" | "unavailable" | "ambiguous";
  tracking_started_at: string | null;
  as_of_timestamp: string;
  latest_observation_at: string | null;
  observed_rx_bytes: number | null;
  observed_tx_bytes: number | null;
  total_observed_bytes: number | null;
  tracking_baseline_bytes: number | null;
  latest_provider_balance_bytes: number | null;
  accounted_remainder_bytes: number | null;
  covered_duration_seconds: number;
  eligible_duration_seconds: number;
  coverage_percent: number | null;
  known_inactive_duration_seconds: number;
  unknown_duration_seconds: number;
  has_coverage_gaps: boolean;
  has_unknown_gaps: boolean;
  interface_name: string | null;
  service_installed: boolean;
  service_expected_to_run: boolean;
  collector_run_status: string | null;
  message: string;
}

export interface AuditBucket {
  start: string;
  end: string;
  observed_rx_bytes: number;
  observed_tx_bytes: number;
  total_observed_bytes: number;
  ending_accounted_remainder_bytes: number | null;
  measured_duration_seconds: number;
  known_inactive_duration_seconds: number;
  unknown_duration_seconds: number;
  state: "measured" | "known_inactive" | "unknown" | "mixed";
}

export interface AuditEvent {
  timestamp: string;
  event_type: string;
  description: string;
  reported_balance_bytes: number | null;
  accounted_remainder_bytes: number | null;
}

export interface AuditComparison {
  start_timestamp: string;
  end_timestamp: string;
  provider_deduction_bytes: number;
  dachik_usage_bytes: number;
  observed_difference_bytes: number;
  evidence_quality: "excellent" | "good" | "limited" | "insufficient";
  conclusion: string;
}

export interface AuditState {
  audit_id: string;
  provider_name: string;
  plan_name: string;
  original_allowance_bytes: number;
  bundle_expiry: string;
  timezone: string;
  audit_status: "in_progress" | "final";
  audit_start: string;
  as_of_timestamp: string;
  initial_tracking_balance_bytes: number | null;
  latest_provider_balance_bytes: number | null;
  total_observed_bytes: number;
  accounted_remainder_bytes: number | null;
  usage_exceeds_starting_balance: boolean;
  latest_trusted_observation: string | null;
  sensor_status: string;
  measured_duration_seconds: number;
  known_inactive_duration_seconds: number;
  unknown_duration_seconds: number;
  evidence_coverage_percent: number;
  evidence_quality: "excellent" | "good" | "limited" | "insufficient";
  has_unknown_gaps: boolean;
  daily: AuditBucket[];
  hourly: AuditBucket[];
  events: AuditEvent[];
  comparisons: AuditComparison[];
}

export interface AuditListItem {
  audit_id: string;
  provider_name: string;
  plan_name: string;
  allowance_bytes: number;
  audit_start: string | null;
  bundle_expiry: string;
  timezone: string;
  status: "draft" | "active" | "completed" | "cancelled";
  is_current: boolean;
}

const NORMAL_DEVELOPMENT_API_URL = "http://127.0.0.1:8765";
const TEST_API_FALLBACK_URL = "http://127.0.0.1:8876";

export function assertSafeAutomatedTestApiUrl(baseUrl: string, mode: string): void {
  if (mode === "test" && baseUrl.replace(/\/$/, "") === NORMAL_DEVELOPMENT_API_URL) {
    throw new Error("Automated frontend tests must not target the normal Dachik development API");
  }
}

const configuredBaseUrl =
  import.meta.env.MODE === "test"
    ? (import.meta.env.VITE_TEST_API_BASE_URL ?? TEST_API_FALLBACK_URL)
    : (import.meta.env.VITE_API_BASE_URL ?? NORMAL_DEVELOPMENT_API_URL);
assertSafeAutomatedTestApiUrl(configuredBaseUrl, import.meta.env.MODE);
const apiBaseUrl = configuredBaseUrl.replace(/\/$/, "");

type Parser<T> = (value: unknown) => T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function parseArray<T>(value: unknown, itemParser: Parser<T>, label: string): T[] {
  if (!Array.isArray(value)) throw new Error(`Invalid ${label} response from Dachik service`);
  return value.map(itemParser);
}

function parseDevice(value: unknown): Device {
  if (
    !isRecord(value) ||
    !["id", "hostname", "display_name", "operating_system", "created_at", "updated_at"].every(
      (key) => typeof value[key] === "string",
    ) ||
    !isNullableString(value.operating_system_version)
  ) {
    throw new Error("Invalid device response from Dachik service");
  }
  return value as unknown as Device;
}

function parseBundle(value: unknown): DataBundle {
  if (
    !isRecord(value) ||
    !["id", "provider_name", "plan_name", "billing_cycle_start", "billing_cycle_end", "timezone", "created_at"].every(
      (key) => typeof value[key] === "string",
    ) ||
    !Number.isSafeInteger(value.allowance_bytes) ||
    Number(value.allowance_bytes) <= 0
  ) {
    throw new Error("Invalid bundle response from Dachik service");
  }
  return value as unknown as DataBundle;
}

function parseExperiment(value: unknown): Experiment {
  if (
    !isRecord(value) ||
    !["id", "data_bundle_id", "device_id", "measurement_boundary", "methodology_version", "status", "created_at"].every(
      (key) => typeof value[key] === "string",
    ) ||
    !isNullableString(value.measurement_source_id) ||
    !isNullableString(value.user_notes) ||
    !isNullableString(value.started_at) ||
    !isNullableString(value.ended_at) ||
    !["draft", "active", "completed", "cancelled"].includes(String(value.status))
  ) {
    throw new Error("Invalid experiment response from Dachik service");
  }
  return value as unknown as Experiment;
}

function parseSnapshot(value: unknown): ISPBalanceSnapshot {
  if (
    !isRecord(value) ||
    !["id", "experiment_id", "timestamp_utc", "reported_value", "reported_unit", "snapshot_type", "provenance", "created_at"].every(
      (key) => typeof value[key] === "string",
    ) ||
    !(value.normalized_bytes === null || Number.isSafeInteger(value.normalized_bytes)) ||
    !isNullableString(value.note) ||
    !isNullableString(value.correction_of_snapshot_id)
  ) {
    throw new Error("Invalid snapshot response from Dachik service");
  }
  return value as unknown as ISPBalanceSnapshot;
}

function parseCurrentUsage(value: unknown): CurrentExperimentUsage {
  if (
    !isRecord(value) ||
    !["status", "message"].every((key) => typeof value[key] === "string") ||
    !["no_active_plan", "multiple_active_plans", "waiting", "active", "paused", "interrupted", "unavailable", "ambiguous"].includes(
      String(value.status),
    ) ||
    !isNullableString(value.experiment_id) ||
    !isNullableString(value.tracking_started_at) ||
    typeof value.as_of_timestamp !== "string" ||
    !isNullableString(value.latest_observation_at) ||
    !isNullableString(value.interface_name) ||
    !isNullableString(value.collector_run_status) ||
    ![
      "observed_rx_bytes",
      "observed_tx_bytes",
      "total_observed_bytes",
      "tracking_baseline_bytes",
      "latest_provider_balance_bytes",
      "accounted_remainder_bytes",
      "coverage_percent",
    ].every(
      (key) => value[key] === null || typeof value[key] === "number",
    ) ||
    !Number.isSafeInteger(value.covered_duration_seconds) ||
    !Number.isSafeInteger(value.eligible_duration_seconds) ||
    !Number.isSafeInteger(value.known_inactive_duration_seconds) ||
    !Number.isSafeInteger(value.unknown_duration_seconds) ||
    typeof value.service_installed !== "boolean" ||
    typeof value.service_expected_to_run !== "boolean" ||
    typeof value.has_coverage_gaps !== "boolean" ||
    typeof value.has_unknown_gaps !== "boolean"
  ) {
    throw new Error("Invalid current usage response from Dachik service");
  }
  return value as unknown as CurrentExperimentUsage;
}

function parseAudit(value: unknown): AuditState {
  if (
    !isRecord(value) ||
    !["audit_id", "provider_name", "plan_name", "audit_status", "audit_start", "as_of_timestamp", "evidence_quality", "timezone"].every(
      (key) => typeof value[key] === "string",
    ) ||
    !Array.isArray(value.daily) ||
    !Array.isArray(value.hourly) ||
    !Array.isArray(value.events) ||
    !Array.isArray(value.comparisons) ||
    !Number.isSafeInteger(value.total_observed_bytes)
  ) {
    throw new Error("Invalid audit response from Dachik service");
  }
  return value as unknown as AuditState;
}

function parseAuditListItem(value: unknown): AuditListItem {
  if (!isRecord(value) || typeof value.audit_id !== "string" || typeof value.provider_name !== "string" || typeof value.timezone !== "string") {
    throw new Error("Invalid audit history response from Dachik service");
  }
  return value as unknown as AuditListItem;
}

function parseHealth(value: unknown): HealthResponse {
  if (
    !isRecord(value) ||
    value.status !== "ok" ||
    value.service !== "dachik" ||
    typeof value.version !== "string"
  ) {
    throw new Error("Invalid health response from Dachik service");
  }
  return value as unknown as HealthResponse;
}

async function request<T>(path: string, parser: Parser<T>, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const detail =
      isRecord(payload) && "detail" in payload
        ? String(payload.detail)
        : `Request failed with status ${response.status}`;
    throw new Error(detail);
  }
  return parser(payload);
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request("/health", parseHealth, { signal });
}

export const dachikApi = {
  listDevices: () => request("/api/v1/devices", (value) => parseArray(value, parseDevice, "devices")),
  createDevice: (payload: Omit<Device, "id" | "created_at" | "updated_at">) =>
    request("/api/v1/devices", parseDevice, { method: "POST", body: JSON.stringify(payload) }),
  listBundles: () => request("/api/v1/bundles", (value) => parseArray(value, parseBundle, "bundles")),
  createBundle: (payload: Omit<DataBundle, "id" | "created_at">) =>
    request("/api/v1/bundles", parseBundle, { method: "POST", body: JSON.stringify(payload) }),
  listExperiments: () =>
    request("/api/v1/experiments", (value) => parseArray(value, parseExperiment, "experiments")),
  createExperiment: (payload: {
    data_bundle_id: string;
    device_id: string;
    measurement_boundary: string;
    methodology_version: string;
    user_notes: string | null;
  }) =>
    request("/api/v1/experiments", parseExperiment, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startExperiment: (id: string, switchCurrent = false) =>
    request(
      `/api/v1/experiments/${id}/start${switchCurrent ? "?switch_current=true" : ""}`,
      parseExperiment,
      { method: "POST" },
    ),
  selectCurrentExperiment: (id: string) =>
    request("/api/v1/tracking/current", parseExperiment, {
      method: "POST",
      body: JSON.stringify({ experiment_id: id }),
    }),
  completeExperiment: (id: string) =>
    request(`/api/v1/experiments/${id}/complete`, parseExperiment, { method: "POST" }),
  listSnapshots: (experimentId: string) =>
    request(`/api/v1/experiments/${experimentId}/isp-snapshots`, (value) =>
      parseArray(value, parseSnapshot, "snapshots"),
    ),
  createSnapshot: (
    experimentId: string,
    payload: Omit<ISPBalanceSnapshot, "id" | "experiment_id" | "normalized_bytes" | "created_at">,
  ) =>
    request(`/api/v1/experiments/${experimentId}/isp-snapshots`, parseSnapshot, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getCurrentExperimentUsage: () =>
    request("/api/v1/usage/current-experiment", parseCurrentUsage),
  getCurrentAudit: () => request("/api/v1/audits/current", parseAudit),
  getAudit: (id: string) => request(`/api/v1/audits/${id}`, parseAudit),
  listAudits: () =>
    request("/api/v1/audits", (value) => parseArray(value, parseAuditListItem, "audit history")),
  downloadAudit: async (id: string, format: "pdf" | "csv" | "json") => {
    const suffix = format === "pdf" ? "report.pdf" : `export.${format}`;
    const response = await fetch(`${apiBaseUrl}/api/v1/audits/${id}/${suffix}`);
    if (!response.ok) throw new Error("Dachik could not generate the audit download");
    return response.blob();
  },
};

export type DachikApi = typeof dachikApi;
