export interface HealthResponse {
  status: "ok";
  service: "dachik";
  version: string;
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8765";
const apiBaseUrl = configuredBaseUrl.replace(/\/$/, "");

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const response = value as Record<string, unknown>;
  return (
    response.status === "ok" &&
    response.service === "dachik" &&
    typeof response.version === "string"
  );
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/health`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }

  const payload: unknown = await response.json();
  if (!isHealthResponse(payload)) {
    throw new Error("Health response did not match the expected schema");
  }

  return payload;
}
