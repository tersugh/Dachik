import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HealthResponse } from "../api/client";
import { ServiceStatus } from "./ServiceStatus";

const health: HealthResponse = {
  status: "ok",
  service: "dachik",
  version: "0.1.0",
};

describe("ServiceStatus", () => {
  it("shows the connecting state before the health request finishes", () => {
    const neverResolves = () => new Promise<HealthResponse>(() => undefined);

    render(<ServiceStatus checkHealth={neverResolves} />);

    expect(screen.getByText("Connecting...")).toBeInTheDocument();
  });

  it("shows the service version when the backend is available", async () => {
    render(<ServiceStatus checkHealth={() => Promise.resolve(health)} />);

    expect(await screen.findByText(/Dachik service online/)).toHaveTextContent("v0.1.0");
  });

  it("shows an unavailable state when the health request fails", async () => {
    render(<ServiceStatus checkHealth={() => Promise.reject(new Error("offline"))} />);

    expect(await screen.findByText("Dachik service unavailable")).toBeInTheDocument();
  });
});
