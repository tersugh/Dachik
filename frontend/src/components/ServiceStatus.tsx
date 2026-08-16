import { useEffect, useState } from "react";

import { getHealth, type HealthResponse } from "../api/client";

type ConnectionState =
  | { kind: "connecting" }
  | { kind: "online"; health: HealthResponse }
  | { kind: "unavailable" };

interface ServiceStatusProps {
  checkHealth?: (signal?: AbortSignal) => Promise<HealthResponse>;
}

export function ServiceStatus({ checkHealth = getHealth }: ServiceStatusProps) {
  const [state, setState] = useState<ConnectionState>({ kind: "connecting" });

  useEffect(() => {
    const controller = new AbortController();

    void checkHealth(controller.signal)
      .then((health) => setState({ kind: "online", health }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState({ kind: "unavailable" });
        }
      });

    return () => controller.abort();
  }, [checkHealth]);

  if (state.kind === "connecting") {
    return <p className="service-status connecting">Connecting...</p>;
  }

  if (state.kind === "unavailable") {
    return <p className="service-status unavailable">Dachik service unavailable</p>;
  }

  return (
    <p className="service-status online">
      Dachik service online <span>v{state.health.version}</span>
    </p>
  );
}
