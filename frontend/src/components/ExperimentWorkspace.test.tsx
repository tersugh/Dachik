import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AuditState,
  CurrentExperimentUsage,
  DachikApi,
  DataBundle,
  Device,
  Experiment,
  ISPBalanceSnapshot,
} from "../api/client";
import { ExperimentWorkspace } from "./ExperimentWorkspace";

const device: Device = {
  id: "device-1",
  hostname: "this-mac",
  display_name: "Tersugh's Mac",
  operating_system: "macOS",
  operating_system_version: null,
  created_at: "2026-08-17T00:00:00Z",
  updated_at: "2026-08-17T00:00:00Z",
};

const bundle: DataBundle = {
  id: "bundle-1",
  provider_name: "MTN Nigeria",
  plan_name: "30GB Monthly",
  allowance_bytes: 30_000_000_000,
  billing_cycle_start: "2026-08-17T00:00:00Z",
  billing_cycle_end: "2026-09-16T00:00:00Z",
  timezone: "Africa/Lagos",
  created_at: "2026-08-17T00:00:00Z",
};

const draft: Experiment = {
  id: "tracking-1",
  data_bundle_id: bundle.id,
  device_id: device.id,
  measurement_source_id: null,
  measurement_boundary: "measured.interface",
  methodology_version: "v1-foundation",
  user_notes: null,
  started_at: null,
  ended_at: null,
  status: "draft",
  created_at: "2026-08-17T00:00:00Z",
};

const active: Experiment = {
  ...draft,
  status: "active",
  started_at: "2026-08-17T00:01:00Z",
};

const waitingUsage: CurrentExperimentUsage = {
  experiment_id: active.id,
  status: "waiting",
  tracking_started_at: active.started_at,
  as_of_timestamp: "2026-08-17T00:01:10Z",
  latest_observation_at: null,
  observed_rx_bytes: null,
  observed_tx_bytes: null,
  total_observed_bytes: null,
  tracking_baseline_bytes: null,
  latest_provider_balance_bytes: null,
  accounted_remainder_bytes: null,
  covered_duration_seconds: 0,
  eligible_duration_seconds: 10,
  coverage_percent: 0,
  known_inactive_duration_seconds: 0,
  unknown_duration_seconds: 0,
  has_coverage_gaps: false,
  has_unknown_gaps: false,
  interface_name: null,
  service_installed: false,
  service_expected_to_run: false,
  collector_run_status: null,
  message: "Waiting for the first measurement.",
};

const auditState: AuditState = {
  audit_id: active.id,
  provider_name: "MTN Nigeria",
  plan_name: "30GB Monthly",
  original_allowance_bytes: 30_000_000_000,
  bundle_expiry: "2026-09-16T00:00:00Z",
  timezone: "Africa/Lagos",
  audit_status: "in_progress",
  audit_start: "2026-08-17T00:01:00Z",
  as_of_timestamp: "2026-08-18T00:00:00Z",
  initial_tracking_balance_bytes: 23_910_000_000,
  latest_provider_balance_bytes: 20_000_000_000,
  total_observed_bytes: 1_000_000_000,
  accounted_remainder_bytes: 22_910_000_000,
  usage_exceeds_starting_balance: false,
  latest_trusted_observation: "2026-08-18T00:00:00Z",
  sensor_status: "active",
  measured_duration_seconds: 3600,
  known_inactive_duration_seconds: 0,
  unknown_duration_seconds: 0,
  evidence_coverage_percent: 100,
  evidence_quality: "excellent",
  has_unknown_gaps: false,
  daily: [],
  hourly: [{
    start: "2026-08-18T00:00:00Z",
    end: "2026-08-18T01:00:00Z",
    observed_rx_bytes: 800_000_000,
    observed_tx_bytes: 200_000_000,
    total_observed_bytes: 1_000_000_000,
    ending_accounted_remainder_bytes: 22_910_000_000,
    measured_duration_seconds: 3600,
    known_inactive_duration_seconds: 0,
    unknown_duration_seconds: 0,
    state: "measured",
  }],
  events: [{
    timestamp: "2026-08-18T19:54:41.725503Z",
    event_type: "measurement_resumed",
    description: "Trusted measurement resumed with a new baseline.",
    reported_balance_bytes: null,
    accounted_remainder_bytes: null,
  }],
  comparisons: [],
};

function snapshot(
  reportedValue: string,
  reportedUnit: string,
  note: string | null = null,
): ISPBalanceSnapshot {
  return {
    id: `snapshot-${reportedValue}`,
    experiment_id: active.id,
    timestamp_utc: "2026-08-17T00:02:00Z",
    reported_value: reportedValue,
    reported_unit: reportedUnit,
    snapshot_type: "remaining_balance",
    normalized_bytes: Number(reportedValue) * (reportedUnit === "GB" ? 1_000_000_000 : 1_000_000),
    provenance: "manual",
    note,
    correction_of_snapshot_id: null,
    created_at: "2026-08-17T00:02:00Z",
  };
}

function createApi(overrides: Partial<DachikApi> = {}): DachikApi {
  return {
    listDevices: vi.fn().mockResolvedValue([device]),
    createDevice: vi.fn().mockResolvedValue(device),
    listBundles: vi.fn().mockResolvedValue([]),
    createBundle: vi.fn().mockResolvedValue(bundle),
    listExperiments: vi.fn().mockResolvedValue([]),
    createExperiment: vi.fn().mockResolvedValue(draft),
    startExperiment: vi.fn().mockResolvedValue(active),
    selectCurrentExperiment: vi.fn().mockResolvedValue(active),
    completeExperiment: vi.fn(),
    listSnapshots: vi.fn().mockResolvedValue([]),
    createSnapshot: vi.fn().mockImplementation((_id, payload) =>
      Promise.resolve(snapshot(payload.reported_value, payload.reported_unit, payload.note)),
    ),
    getCurrentExperimentUsage: vi.fn().mockResolvedValue(waitingUsage),
    getCurrentAudit: vi.fn().mockResolvedValue(auditState),
    getAudit: vi.fn().mockResolvedValue(auditState),
    listAudits: vi.fn().mockResolvedValue([]),
    downloadAudit: vi.fn().mockResolvedValue(new Blob()),
    ...overrides,
  };
}

async function waitForSetup(): Promise<void> {
  await screen.findByRole("heading", { name: /Tell Dachik about your plan/ });
}

function fillBasicPlan(size = "30"): void {
  fireEvent.change(screen.getByLabelText("Network / provider"), { target: { value: "MTN Nigeria" } });
  fireEvent.change(screen.getByLabelText(/Plan name/), { target: { value: "30GB Monthly" } });
  fireEvent.change(screen.getByLabelText("How much data?"), { target: { value: size } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("consumer data-plan workflow", () => {
  it("starts a 30 GB, 30-day newly activated plan on the single local Mac", async () => {
    const api = createApi();
    render(<ExperimentWorkspace api={api} />);
    await waitForSetup();
    fillBasicPlan();
    fireEvent.change(screen.getByLabelText("Started"), { target: { value: "2026-08-17" } });
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));

    await screen.findByText("Tracking setup complete");
    expect(api.createDevice).not.toHaveBeenCalled();
    expect(api.createBundle).toHaveBeenCalledWith(
      expect.objectContaining({ allowance_bytes: 30_000_000_000 }),
    );
    const createdPlan = vi.mocked(api.createBundle).mock.calls[0]?.[0];
    expect(
      new Date(createdPlan?.billing_cycle_end ?? 0).getTime() -
        new Date(createdPlan?.billing_cycle_start ?? 0).getTime(),
    ).toBe(30 * 24 * 60 * 60 * 1000);
    expect(api.createExperiment).toHaveBeenCalledWith(
      expect.objectContaining({ data_bundle_id: bundle.id, device_id: device.id }),
    );
    expect(api.startExperiment).toHaveBeenCalledWith(draft.id, false);
    expect(api.createSnapshot).toHaveBeenCalledWith(
      active.id,
      expect.objectContaining({ reported_value: "30", reported_unit: "GB", snapshot_type: "remaining_balance" }),
    );
    expect(screen.getByText("MTN Nigeria · 30 GB")).toBeInTheDocument();
    expect(screen.getByText("Tersugh's Mac")).toBeInTheDocument();
    expect(screen.getByText("Waiting for the first measurement.")).toBeInTheDocument();
    expect(screen.queryByText(/Used: 0/)).not.toBeInTheDocument();
    expect(screen.queryByText("measured.interface")).not.toBeInTheDocument();
    expect(screen.queryByText(/experiment/i)).not.toBeInTheDocument();
  });

  it("supports custom expiry, transparent device creation, and an existing 25 GB balance", async () => {
    const api = createApi({ listDevices: vi.fn().mockResolvedValue([]) });
    render(<ExperimentWorkspace api={api} />);
    await waitForSetup();
    fillBasicPlan();
    fireEvent.change(screen.getByLabelText("How long is it valid?"), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("Started"), { target: { value: "2026-08-17" } });
    fireEvent.change(screen.getByLabelText("Expires"), { target: { value: "2026-08-25" } });
    fireEvent.change(screen.getByLabelText(/Name this Mac/), { target: { value: "Home Mac" } });
    fireEvent.click(screen.getByLabelText("I’ve already used some data"));
    fireEvent.change(screen.getByLabelText("Current network balance"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));

    await screen.findByText("Tracking setup complete");
    expect(api.createDevice).toHaveBeenCalledWith(expect.objectContaining({ display_name: "Home Mac" }));
    expect(api.createBundle).toHaveBeenCalledWith(
      expect.objectContaining({ allowance_bytes: 30_000_000_000 }),
    );
    const customPlan = vi.mocked(api.createBundle).mock.calls[0]?.[0];
    expect(
      new Date(customPlan?.billing_cycle_end ?? 0).getTime() -
        new Date(customPlan?.billing_cycle_start ?? 0).getTime(),
    ).toBe(8 * 24 * 60 * 60 * 1000);
    expect(api.createSnapshot).toHaveBeenCalledWith(
      active.id,
      expect.objectContaining({ reported_value: "25", reported_unit: "GB" }),
    );
  });

  it("creates an MB plan without exposing raw bytes", async () => {
    const mbBundle = { ...bundle, allowance_bytes: 750_000_000, plan_name: "750 MB plan" };
    const api = createApi({ createBundle: vi.fn().mockResolvedValue(mbBundle) });
    render(<ExperimentWorkspace api={api} />);
    await waitForSetup();
    fillBasicPlan("750");
    fireEvent.change(screen.getByLabelText("Data unit"), { target: { value: "MB" } });
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));

    await screen.findByText("Tracking setup complete");
    expect(api.createBundle).toHaveBeenCalledWith(
      expect.objectContaining({ allowance_bytes: 750_000_000 }),
    );
    expect(api.createSnapshot).toHaveBeenCalledWith(
      active.id,
      expect.objectContaining({ reported_value: "750", reported_unit: "MB" }),
    );
    expect(screen.queryByText(/allowance in bytes/i)).not.toBeInTheDocument();
  });

  it("updates network balance and records confirmed network-reported exhaustion immutably", async () => {
    const initial = snapshot("25", "GB");
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      listSnapshots: vi.fn().mockResolvedValue([initial]),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ExperimentWorkspace api={api} />);

    await screen.findByText("Current network balance");
    expect(await screen.findByText("25 GB")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Data remaining"), { target: { value: "24.6" } });
    fireEvent.change(screen.getByLabelText("Optional source"), { target: { value: "USSD" } });
    fireEvent.change(screen.getByLabelText("Optional note"), { target: { value: "Checked manually" } });
    fireEvent.click(screen.getByRole("button", { name: "Save balance" }));

    await waitFor(() => expect(api.createSnapshot).toHaveBeenCalledWith(
      active.id,
      expect.objectContaining({
        reported_value: "24.6",
        reported_unit: "GB",
        provenance: "manual",
        note: "Source: USSD · Checked manually",
      }),
    ));
    fireEvent.click(screen.getByRole("button", { name: "My network says my data is finished" }));
    await waitFor(() => expect(api.createSnapshot).toHaveBeenCalledWith(
      active.id,
      expect.objectContaining({ reported_value: "0", snapshot_type: "remaining_balance", provenance: "manual" }),
    ));
    expect(window.confirm).toHaveBeenCalled();
    expect(screen.queryByText(/ISP balance snapshot|measurement boundary/i)).not.toBeInTheDocument();
  });

  it("shows real observed usage and an accounted remainder without implying an ISP balance", async () => {
    const measuredUsage: CurrentExperimentUsage = {
      ...waitingUsage,
      status: "active",
      latest_observation_at: "2026-08-17T00:10:00Z",
      observed_rx_bytes: 2_000_000_000,
      observed_tx_bytes: 400_000_000,
      total_observed_bytes: 2_400_000_000,
      tracking_baseline_bytes: 30_000_000_000,
      accounted_remainder_bytes: 27_600_000_000,
      covered_duration_seconds: 500,
      eligible_duration_seconds: 600,
      coverage_percent: 83.3,
      has_coverage_gaps: true,
      has_unknown_gaps: true,
      unknown_duration_seconds: 100,
      interface_name: "en0",
      message: "Dachik is observing this Mac.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(measuredUsage),
    });
    render(<ExperimentWorkspace api={api} />);

    expect(await screen.findByText("2.4 GB")).toBeInTheDocument();
    expect(screen.getByText("27.6 GB")).toBeInTheDocument();
    expect(screen.getByText("Some usage may not have been observed during an earlier tracking gap.")).toBeInTheDocument();
    expect(screen.getByText(/Starts from the network balance recorded when tracking began/)).toBeInTheDocument();
    expect(screen.queryByText(/counter|usage interval|measured\.interface/i)).not.toBeInTheDocument();
  });

  it("shows healthy tracking without a permanent gap warning", async () => {
    const healthyUsage: CurrentExperimentUsage = {
      ...waitingUsage,
      status: "active",
      latest_observation_at: "2026-08-17T00:10:00Z",
      observed_rx_bytes: 1_000,
      observed_tx_bytes: 500,
      total_observed_bytes: 1_500,
      tracking_baseline_bytes: 30_000_000_000,
      accounted_remainder_bytes: 29_999_998_500,
      service_installed: true,
      service_expected_to_run: true,
      collector_run_status: "running",
      message: "Dachik is observing this Mac.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(healthyUsage),
    });

    render(<ExperimentWorkspace api={api} />);

    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(screen.queryByText(/Some usage may not have been observed/)).not.toBeInTheDocument();
  });

  it("opens a simple continuously available audit view", async () => {
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
    });
    render(<ExperimentWorkspace api={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "View audit" }));

    expect(await screen.findByRole("heading", { name: "MTN Nigeria" })).toBeInTheDocument();
    expect(screen.getByText("Your data audit")).toBeInTheDocument();
    expect(screen.getAllByText("1 GB")).not.toHaveLength(0);
    expect(screen.getByText(/Excellent · 100%/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Daily breakdown" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Hourly ledger" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download audit" })).toBeInTheDocument();
    expect(screen.getByText("Times shown in Africa/Lagos")).toBeInTheDocument();
    expect(screen.getAllByText("01:00–02:00")).not.toHaveLength(0);
    expect(screen.getByText("18 Aug 2026 · 20:54:41")).toBeInTheDocument();
    expect(screen.queryByText(/2026-08-\d\dT/)).not.toBeInTheDocument();
    expect(screen.queryByText(/CounterSeries|UsageInterval|measurement_boundary/)).not.toBeInTheDocument();
  });

  it("requires an explicit decision before switching from the current plan", async () => {
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
    });
    render(<ExperimentWorkspace api={api} />);

    fireEvent.click(await screen.findByRole("button", { name: "Track another plan" }));
    expect(screen.getByText("You’re already tracking")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep tracking this plan" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch tracking plan" }));
    await waitForSetup();
    fillBasicPlan();
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));

    await waitFor(() => expect(api.startExperiment).toHaveBeenCalledWith(draft.id, true));
  });

  it("shows a consumer plan chooser when active plans are ambiguous", async () => {
    const secondBundle: DataBundle = {
      ...bundle,
      id: "bundle-2",
      provider_name: "Airtel NG",
      plan_name: "15 GB plan",
      allowance_bytes: 15_000_000_000,
    };
    const secondExperiment: Experiment = {
      ...active,
      id: "experiment-2",
      data_bundle_id: secondBundle.id,
    };
    const ambiguousUsage: CurrentExperimentUsage = {
      ...waitingUsage,
      experiment_id: null,
      status: "multiple_active_plans",
      message: "Dachik found more than one active data plan. Choose which one to track.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle, secondBundle]),
      listExperiments: vi.fn().mockResolvedValue([active, secondExperiment]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(ambiguousUsage),
    });
    render(<ExperimentWorkspace api={api} />);

    expect(
      await screen.findByRole("heading", {
        name: "Dachik found more than one active data plan.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("MTN Nigeria · 30 GB")).toBeInTheDocument();
    expect(screen.getByText("Airtel NG · 15 GB")).toBeInTheDocument();
    expect(screen.queryByText(/measured\.interface|experiment-/)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Track this plan" })[0]!);
    await waitFor(() => expect(api.selectCurrentExperiment).toHaveBeenCalledWith(active.id));
  });

  it("does not describe a known non-attributable period as unknown usage", async () => {
    const usage: CurrentExperimentUsage = {
      ...waitingUsage,
      status: "active",
      known_inactive_duration_seconds: 600,
      has_coverage_gaps: false,
      has_unknown_gaps: false,
      message: "Dachik is observing this Mac.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(usage),
    });

    render(<ExperimentWorkspace api={api} />);

    await screen.findByText("Active");
    expect(screen.queryByText(/Some usage may not have been observed/)).not.toBeInTheDocument();
  });

  it("shows a simple paused state when the sensor service is stopped", async () => {
    const pausedUsage: CurrentExperimentUsage = {
      ...waitingUsage,
      status: "paused",
      service_installed: true,
      service_expected_to_run: false,
      collector_run_status: "stopped",
      message: "Tracking is currently paused.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(pausedUsage),
    });

    render(<ExperimentWorkspace api={api} />);

    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("Tracking is currently paused.")).toBeInTheDocument();
    expect(screen.queryByText(/Used: 0/)).not.toBeInTheDocument();
  });

  it("keeps the starting balance as the accounted baseline after later balance updates", async () => {
    const initial = snapshot("23.91", "GB");
    const later = {
      ...snapshot("20", "GB"),
      id: "snapshot-later",
      timestamp_utc: "2026-08-18T00:02:00Z",
      created_at: "2026-08-18T00:02:00Z",
    };
    const usage: CurrentExperimentUsage = {
      ...waitingUsage,
      status: "active",
      latest_observation_at: "2026-08-18T00:01:00Z",
      observed_rx_bytes: 200_000,
      observed_tx_bytes: 15_200,
      total_observed_bytes: 215_200,
      tracking_baseline_bytes: 23_910_000_000,
      accounted_remainder_bytes: 23_909_784_800,
      message: "Dachik is observing this Mac.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      listSnapshots: vi.fn().mockResolvedValue([initial, later]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(usage),
    });

    render(<ExperimentWorkspace api={api} />);

    expect(await screen.findByText("215.2 KB")).toBeInTheDocument();
    expect(screen.getByText("20 GB")).toBeInTheDocument();
    expect(screen.getByText("23.91 GB")).toBeInTheDocument();
    expect(screen.getByText("MTN Nigeria · 30 GB")).toBeInTheDocument();
  });

  it("shows an unknown remainder when no tracking balance baseline exists", async () => {
    const usage: CurrentExperimentUsage = {
      ...waitingUsage,
      status: "active",
      observed_rx_bytes: 1_000,
      observed_tx_bytes: 0,
      total_observed_bytes: 1_000,
      message: "Dachik is observing this Mac.",
    };
    const api = createApi({
      listBundles: vi.fn().mockResolvedValue([bundle]),
      listExperiments: vi.fn().mockResolvedValue([active]),
      getCurrentExperimentUsage: vi.fn().mockResolvedValue(usage),
    });

    render(<ExperimentWorkspace api={api} />);

    expect(await screen.findByText("1 KB")).toBeInTheDocument();
    expect(screen.getByText("Accounted remainder").nextElementSibling).toHaveTextContent("Unknown");
  });

  it("shows a friendly failure and never claims tracking started", async () => {
    const api = createApi({ createBundle: vi.fn().mockRejectedValue(new Error("Your plan could not be saved")) });
    render(<ExperimentWorkspace api={api} />);
    await waitForSetup();
    fillBasicPlan();
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Your plan could not be saved");
    expect(screen.queryByText("Tracking setup complete")).not.toBeInTheDocument();
  });
});
