import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
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
    completeExperiment: vi.fn(),
    listSnapshots: vi.fn().mockResolvedValue([]),
    createSnapshot: vi.fn().mockImplementation((_id, payload) =>
      Promise.resolve(snapshot(payload.reported_value, payload.reported_unit, payload.note)),
    ),
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
    expect(api.startExperiment).toHaveBeenCalledWith(draft.id);
    expect(api.createSnapshot).toHaveBeenCalledWith(
      active.id,
      expect.objectContaining({ reported_value: "30", reported_unit: "GB", snapshot_type: "remaining_balance" }),
    );
    expect(screen.getByText("MTN Nigeria · 30 GB")).toBeInTheDocument();
    expect(screen.getByText("Tersugh's Mac")).toBeInTheDocument();
    expect(screen.getByText("Measurement sensor not running yet.")).toBeInTheDocument();
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
    expect(screen.getByText("25 GB")).toBeInTheDocument();
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
    expect(screen.queryByText(/ISP balance snapshot|measurement boundary|audit/i)).not.toBeInTheDocument();
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
