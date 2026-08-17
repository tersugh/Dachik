import type { DataBundle, Device, Experiment } from "../api/client";

export interface ExperimentPresentation {
  primaryLabel: string;
  deviceStatus: string;
  dateLabel: string;
  boundaryLabel: string;
}

const BOUNDARY_LABELS: Record<string, string> = {
  "measured.interface": "Local Mac interface",
  "attributed.process": "Application attribution",
  "measured.gateway_wan": "Gateway WAN",
  "attributed.device": "Gateway device attribution",
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function presentExperiment(
  experiment: Experiment,
  devices: Device[],
  bundles: DataBundle[],
): ExperimentPresentation {
  const device = devices.find((candidate) => candidate.id === experiment.device_id);
  const bundle = bundles.find((candidate) => candidate.id === experiment.data_bundle_id);
  const eventDate = experiment.started_at ?? experiment.created_at;
  return {
    primaryLabel: bundle
      ? `${bundle.provider_name} · ${bundle.plan_name}`
      : "Data Audit Experiment",
    deviceStatus: `${device?.display_name ?? "Unknown device"} · ${experiment.status.toUpperCase()}`,
    dateLabel: `${experiment.started_at ? "Started" : "Created"} ${formatDate(eventDate)}`,
    boundaryLabel: BOUNDARY_LABELS[experiment.measurement_boundary] ?? "Other measurement source",
  };
}
