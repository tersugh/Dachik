import { describe, expect, it } from "vitest";

import type { DataBundle, Device, Experiment } from "../api/client";
import { presentExperiment } from "./experimentPresentation";

const device = { id: "device-1", display_name: "Tersugh's Mac" } as Device;
const bundle = {
  id: "bundle-1",
  provider_name: "MTN Nigeria",
  plan_name: "30GB Monthly",
} as DataBundle;
const experiment = {
  id: "experiment-1",
  device_id: device.id,
  data_bundle_id: bundle.id,
  measurement_boundary: "measured.interface",
  status: "active",
  started_at: "2026-08-17T00:00:00Z",
  created_at: "2026-08-16T23:59:00Z",
} as Experiment;

describe("experiment presentation", () => {
  it("uses bundle, device, status, date, and a friendly boundary label", () => {
    const presentation = presentExperiment(experiment, [device], [bundle]);

    expect(presentation.primaryLabel).toBe("MTN Nigeria · 30GB Monthly");
    expect(presentation.deviceStatus).toBe("Tersugh's Mac · ACTIVE");
    expect(presentation.dateLabel).toBe("Started 17 Aug 2026");
    expect(presentation.boundaryLabel).toBe("Local Mac interface");
    expect(Object.values(presentation)).not.toContain("measured.interface");
  });
});
