import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  dachikApi,
  type DachikApi,
  type DataBundle,
  type Device,
  type Experiment,
  type ISPBalanceSnapshot,
  type CurrentExperimentUsage,
} from "../api/client";
import {
  bundleSizeToBytes,
  formatBundleSize,
  formatObservedBytes,
  type BundleUnit,
} from "../domain/bundleSize";

type ValidityChoice = "7" | "14" | "30" | "custom";
type StartingBalanceChoice = "new" | "used";

function todayInputValue(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function dateInputToLocalDate(value: string, label: string): Date {
  const date = new Date(`${value}T00:00:00`);
  if (!value || Number.isNaN(date.getTime())) throw new Error(`${label} is not a valid date`);
  return date;
}

function deriveExpiry(startValue: string, validity: ValidityChoice, customExpiry: string): Date {
  const start = dateInputToLocalDate(startValue, "Plan start");
  if (validity === "custom") {
    const expiry = dateInputToLocalDate(customExpiry, "Expiry date");
    if (expiry <= start) throw new Error("Expiry date must be after the plan start date");
    return expiry;
  }
  const expiry = new Date(start);
  expiry.setDate(expiry.getDate() + Number(validity));
  return expiry;
}

function friendlyDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(value));
}

function deviceForSetup(devices: Device[], selectedId: string): Device | null {
  const localDevices = devices.filter((device) => device.operating_system === "macOS");
  if (localDevices.length === 1) return localDevices[0] ?? null;
  return localDevices.find((device) => device.id === selectedId) ?? null;
}

function combineSourceAndNote(source: string, note: string): string | null {
  const parts = [source ? `Source: ${source}` : "", note.trim()].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

function trackingLabel(status: CurrentExperimentUsage["status"] | undefined): string {
  if (status === "active") return "Active";
  if (status === "paused" || status === "interrupted") return "Paused";
  if (status === "unavailable" || status === "ambiguous") return "Unavailable";
  return "Starting…";
}

interface ExperimentWorkspaceProps {
  api?: DachikApi;
}

export function ExperimentWorkspace({ api = dachikApi }: ExperimentWorkspaceProps) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [bundles, setBundles] = useState<DataBundle[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [snapshots, setSnapshots] = useState<ISPBalanceSnapshot[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [bundleUnit, setBundleUnit] = useState<BundleUnit>("GB");
  const [balanceUnit, setBalanceUnit] = useState<BundleUnit>("GB");
  const [validity, setValidity] = useState<ValidityChoice>("30");
  const [startDate, setStartDate] = useState(todayInputValue);
  const [customExpiry, setCustomExpiry] = useState("");
  const [startingBalance, setStartingBalance] = useState<StartingBalanceChoice>("new");
  const [showAnotherPlan, setShowAnotherPlan] = useState(false);
  const [showSwitchPrompt, setShowSwitchPrompt] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [usage, setUsage] = useState<CurrentExperimentUsage | null>(null);

  const activeExperiments = useMemo(
    () => experiments.filter((experiment) => experiment.status === "active"),
    [experiments],
  );
  const activeExperiment = useMemo(() => {
    if (usage?.experiment_id) {
      return experiments.find((experiment) => experiment.id === usage.experiment_id) ?? null;
    }
    if (usage?.status === "multiple_active_plans") return null;
    return activeExperiments.length === 1 ? activeExperiments[0] ?? null : null;
  }, [activeExperiments, experiments, usage]);
  const activeBundle = useMemo(
    () => bundles.find((bundle) => bundle.id === activeExperiment?.data_bundle_id) ?? null,
    [activeExperiment, bundles],
  );
  const activeDevice = useMemo(
    () => devices.find((device) => device.id === activeExperiment?.device_id) ?? null,
    [activeExperiment, devices],
  );
  const setupDevice = deviceForSetup(devices, selectedDeviceId);
  const localDevices = devices.filter((device) => device.operating_system === "macOS");

  useEffect(() => {
    let mounted = true;
    void Promise.all([api.listDevices(), api.listBundles(), api.listExperiments()])
      .then(([nextDevices, nextBundles, nextExperiments]) => {
        if (!mounted) return;
        setDevices(nextDevices);
        setBundles(nextBundles);
        setExperiments(nextExperiments);
        const macs = nextDevices.filter((device) => device.operating_system === "macOS");
        if (macs.length === 1) setSelectedDeviceId(macs[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (mounted) setError(reason instanceof Error ? reason.message : "Dachik could not load your plans");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [api]);

  useEffect(() => {
    if (!activeExperiment) return;
    let mounted = true;
    void api
      .listSnapshots(activeExperiment.id)
      .then((items) => {
        if (mounted) setSnapshots(items);
      })
      .catch((reason: unknown) => {
        if (mounted) setError(reason instanceof Error ? reason.message : "Dachik could not load the network balance");
      });
    return () => {
      mounted = false;
    };
  }, [activeExperiment, api]);

  useEffect(() => {
    if (loading) return;
    let mounted = true;
    const refreshUsage = () => {
      void api
        .getCurrentExperimentUsage()
        .then((value) => {
          if (mounted) setUsage(value);
        })
        .catch((reason: unknown) => {
          if (mounted) setError(reason instanceof Error ? reason.message : "Dachik could not load measured usage");
        });
    };
    refreshUsage();
    const timer = window.setInterval(refreshUsage, 10_000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [api, loading]);

  async function run(actionName: string, action: () => Promise<void>) {
    if (busyAction) return;
    setBusyAction(actionName);
    setError(null);
    setSuccess(null);
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dachik could not complete that action");
    } finally {
      setBusyAction(null);
    }
  }

  function startTracking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void run("start", async () => {
      const amount = String(data.get("bundle_size"));
      const allowanceBytes = bundleSizeToBytes(amount, bundleUnit);
      const expiry = deriveExpiry(startDate, validity, customExpiry);
      let device = setupDevice;
      if (!device) {
        const friendlyName = String(data.get("device_name")).trim() || "This Mac";
        device = await api.createDevice({
          hostname: "this-mac",
          display_name: friendlyName,
          operating_system: "macOS",
          operating_system_version: null,
        });
        setDevices((current) => [device as Device, ...current]);
        setSelectedDeviceId(device.id);
      }
      const bundle = await api.createBundle({
        provider_name: String(data.get("provider_name")).trim(),
        plan_name: String(data.get("plan_name")).trim() || `${amount} ${bundleUnit} plan`,
        allowance_bytes: allowanceBytes,
        billing_cycle_start: dateInputToLocalDate(startDate, "Plan start").toISOString(),
        billing_cycle_end: expiry.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      setBundles((current) => [bundle, ...current]);
      const draft = await api.createExperiment({
        data_bundle_id: bundle.id,
        device_id: device.id,
        measurement_boundary: "measured.interface",
        methodology_version: "v1-foundation",
        user_notes: null,
      });
      const tracking = await api.startExperiment(draft.id, showAnotherPlan);
      const reportedValue =
        startingBalance === "new" ? amount : String(data.get("current_balance")).trim();
      const reportedUnit = startingBalance === "new" ? bundleUnit : balanceUnit;
      const initialBalance = await api.createSnapshot(tracking.id, {
        timestamp_utc: new Date().toISOString(),
        reported_value: reportedValue,
        reported_unit: reportedUnit,
        snapshot_type: "remaining_balance",
        provenance: "manual",
        note:
          startingBalance === "new"
            ? "User said this plan was just activated"
            : "Current network balance when tracking started",
        correction_of_snapshot_id: null,
      });
      setExperiments((current) => [tracking, ...current]);
      setSnapshots([initialBalance]);
      setUsage(null);
      setShowAnotherPlan(false);
      setShowSwitchPrompt(false);
      setSuccess("Tracking setup complete.");
      form.reset();
    });
  }

  function chooseCurrentPlan(experiment: Experiment) {
    void run("choose-plan", async () => {
      await api.selectCurrentExperiment(experiment.id);
      const currentUsage = await api.getCurrentExperimentUsage();
      setUsage(currentUsage);
      setSuccess("Tracking plan selected.");
    });
  }

  function updateBalance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeExperiment) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    void run("balance", async () => {
      const checkedAt = String(data.get("checked_at"));
      const timestamp = checkedAt ? new Date(checkedAt) : new Date();
      if (Number.isNaN(timestamp.getTime())) throw new Error("Checked at is not a valid date and time");
      const snapshot = await api.createSnapshot(activeExperiment.id, {
        timestamp_utc: timestamp.toISOString(),
        reported_value: String(data.get("reported_value")).trim(),
        reported_unit: String(data.get("reported_unit")),
        snapshot_type: "remaining_balance",
        provenance: "manual",
        note: combineSourceAndNote(String(data.get("source")), String(data.get("note"))),
        correction_of_snapshot_id: null,
      });
      setSnapshots((current) => [...current, snapshot]);
      setSuccess("Network balance saved.");
      form.reset();
    });
  }

  function reportExhausted() {
    if (!activeExperiment || !window.confirm("Record that your network says this plan has no data left?")) return;
    void run("exhausted", async () => {
      const snapshot = await api.createSnapshot(activeExperiment.id, {
        timestamp_utc: new Date().toISOString(),
        reported_value: "0",
        reported_unit: activeBundle && activeBundle.allowance_bytes < 1_000_000_000 ? "MB" : "GB",
        snapshot_type: "remaining_balance",
        provenance: "manual",
        note: "User reported that the network says this plan is exhausted",
        correction_of_snapshot_id: null,
      });
      setSnapshots((current) => [...current, snapshot]);
      setSuccess("Network-reported exhaustion saved. Dachik has not compared this with measurements yet.");
    });
  }

  if (loading) return <section className="workspace"><p className="form-notice">Loading your data plan…</p></section>;

  const latestBalance = snapshots.at(-1) ?? null;
  const showSetup = !activeExperiment || showAnotherPlan;
  const busy = busyAction !== null;

  return (
    <section className="workspace" aria-labelledby="plan-heading">
      {error && <p className="form-error" role="alert">{error}</p>}
      {success && <p className="form-success" role="status">{success}</p>}

      {usage?.status === "multiple_active_plans" ? (
        <div className="plan-setup">
          <div className="section-heading">
            <p className="eyebrow">Choose your data plan</p>
            <h2 id="plan-heading">Dachik found more than one active data plan.</h2>
            <p>Choose which one you want to track on this Mac.</p>
          </div>
          <div className="plan-choice-list">
            {activeExperiments.map((experiment) => {
              const bundle = bundles.find((item) => item.id === experiment.data_bundle_id);
              if (!bundle) return null;
              return (
                <div className="panel" key={experiment.id}>
                  <strong>{bundle.provider_name} · {formatBundleSize(bundle.allowance_bytes)}</strong>
                  <span>{bundle.plan_name}</span>
                  <span>Valid until {friendlyDate(bundle.billing_cycle_end)}</span>
                  <button disabled={busy} type="button" onClick={() => chooseCurrentPlan(experiment)}>
                    Track this plan
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : showSwitchPrompt && activeBundle ? (
        <div className="plan-setup">
          <div className="section-heading">
            <p className="eyebrow">You’re already tracking</p>
            <h2 id="plan-heading">{activeBundle.provider_name} · {formatBundleSize(activeBundle.allowance_bytes)}</h2>
            <p>{activeBundle.plan_name} · Valid until {friendlyDate(activeBundle.billing_cycle_end)}</p>
            <p>Dachik currently tracks one data plan on this Mac at a time.</p>
          </div>
          <div className="button-row">
            <button type="button" onClick={() => setShowSwitchPrompt(false)}>Keep tracking this plan</button>
            <button className="secondary" type="button" onClick={() => { setShowSwitchPrompt(false); setShowAnotherPlan(true); }}>Switch tracking plan</button>
          </div>
        </div>
      ) : showSetup ? (
        <div className="plan-setup">
          <div className="section-heading">
            <p className="eyebrow">Add your data plan</p>
            <h2 id="plan-heading">Tell Dachik about your plan and start tracking it.</h2>
            <p>Dachik keeps your plan details and your network’s reported balance together on this Mac.</p>
          </div>
          <form className="plan-form panel" onSubmit={startTracking}>
            <label>Network / provider<input name="provider_name" required placeholder="MTN Nigeria" /></label>
            <label>Plan name <span className="optional">Optional</span><input name="plan_name" placeholder="30GB Monthly" /></label>
            <fieldset className="bundle-size-field">
              <legend>How much data?</legend>
              <input aria-label="How much data?" name="bundle_size" inputMode="decimal" required placeholder="30" />
              <select aria-label="Data unit" value={bundleUnit} onChange={(event) => setBundleUnit(event.target.value as BundleUnit)}>
                <option value="MB">MB</option><option value="GB">GB</option>
              </select>
            </fieldset>
            <label>How long is it valid?
              <select aria-label="How long is it valid?" value={validity} onChange={(event) => setValidity(event.target.value as ValidityChoice)}>
                <option value="7">7 days</option><option value="14">14 days</option><option value="30">30 days</option><option value="custom">Custom expiry date</option>
              </select>
            </label>
            <label>Started<input aria-label="Started" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required /></label>
            {validity === "custom" && <label>Expires<input aria-label="Expires" type="date" value={customExpiry} onChange={(event) => setCustomExpiry(event.target.value)} required /></label>}

            {localDevices.length === 0 && <label>Name this Mac <span className="optional">Optional</span><input name="device_name" placeholder="This Mac" /></label>}
            {localDevices.length === 1 && <p className="device-note">Tracking on <strong>{localDevices[0]?.display_name}</strong></p>}
            {localDevices.length > 1 && <label>Which Mac?
              <select aria-label="Which Mac?" value={selectedDeviceId} onChange={(event) => setSelectedDeviceId(event.target.value)} required>
                <option value="">Choose this Mac</option>{localDevices.map((device) => <option key={device.id} value={device.id}>{device.display_name}</option>)}
              </select>
            </label>}

            <fieldset className="choice-group">
              <legend>What is your current network balance?</legend>
              <label><input type="radio" name="balance_state" checked={startingBalance === "new"} onChange={() => setStartingBalance("new")} />I just activated this plan</label>
              <label><input type="radio" name="balance_state" checked={startingBalance === "used"} onChange={() => setStartingBalance("used")} />I’ve already used some data</label>
            </fieldset>
            {startingBalance === "used" && <fieldset className="bundle-size-field">
              <legend>How much data does your network say you have left?</legend>
              <input aria-label="Current network balance" name="current_balance" inputMode="decimal" required placeholder="25" />
              <select aria-label="Current balance unit" value={balanceUnit} onChange={(event) => setBalanceUnit(event.target.value as BundleUnit)}>
                <option value="MB">MB</option><option value="GB">GB</option>
              </select>
            </fieldset>}
            <button disabled={busy || (localDevices.length > 1 && !selectedDeviceId)} type="submit">{busyAction === "start" ? "Starting…" : "Start tracking"}</button>
          </form>
        </div>
      ) : activeBundle && activeExperiment ? (
        <div className="active-plan">
          <div className="active-plan-heading">
            <div>
              <p className="eyebrow">Tracking active</p>
              <h2 id="plan-heading">{activeBundle.provider_name} · {formatBundleSize(activeBundle.allowance_bytes)}</h2>
              <p className="plan-name">{activeBundle.plan_name}</p>
            </div>
            <button className="secondary compact" type="button" onClick={() => setShowSwitchPrompt(true)}>Track another plan</button>
          </div>
          <dl className="plan-facts">
            <div><dt>Valid until</dt><dd>{friendlyDate(activeBundle.billing_cycle_end)}</dd></div>
            <div><dt>This Mac</dt><dd>{activeDevice?.display_name ?? "Local Mac"}</dd></div>
            <div><dt>Current network balance</dt><dd>{latestBalance ? `${latestBalance.reported_value} ${latestBalance.reported_unit}` : "Unknown"}</dd></div>
            <div><dt>Tracking</dt><dd>{trackingLabel(usage?.status)}</dd></div>
          </dl>
          {usage?.total_observed_bytes === null || !usage ? (
            <div className="sensor-notice"><strong>Tracking setup complete</strong><span>{usage?.message ?? "Waiting for the first measurement."}</span></div>
          ) : (
            <div className="usage-summary">
              <div><span>Used according to Dachik</span><strong>{formatObservedBytes(usage.total_observed_bytes)}</strong></div>
              <div><span>Accounted remainder</span><strong>{usage.accounted_remainder_bytes === null ? "Unknown" : formatObservedBytes(usage.accounted_remainder_bytes)}</strong></div>
              <p>Starts from the network balance recorded when tracking began and subtracts only traffic Dachik observed on this Mac. It is not your network’s official balance.</p>
            </div>
          )}
          {usage?.total_observed_bytes !== null && (usage?.status === "paused" || usage?.status === "interrupted") && <p className="coverage-warning">Tracking is currently paused.</p>}
          {usage?.total_observed_bytes !== null && (usage?.status === "unavailable" || usage?.status === "ambiguous") && <p className="coverage-warning">Tracking is currently unavailable.</p>}
          {usage?.has_unknown_gaps && <p className="coverage-warning">Some usage may not have been observed during an earlier tracking gap.</p>}

          <form className="balance-form panel" onSubmit={updateBalance}>
            <h3>Update network balance</h3>
            <fieldset className="bundle-size-field">
              <legend>How much data does your network say you have left?</legend>
              <input aria-label="Data remaining" name="reported_value" inputMode="decimal" required placeholder="24.6" />
              <select aria-label="Remaining balance unit" name="reported_unit" defaultValue="GB"><option value="MB">MB</option><option value="GB">GB</option></select>
            </fieldset>
            <label>Checked at <span className="optional">Leave blank for now</span><input name="checked_at" type="datetime-local" /></label>
            <label>Optional source<select name="source" defaultValue=""><option value="">Not specified</option><option value="provider app">Provider app</option><option value="SMS">SMS</option><option value="USSD">USSD</option><option value="website">Website</option><option value="other">Other</option></select></label>
            <label>Optional note<textarea name="note" rows={2} /></label>
            <button disabled={busy} type="submit">{busyAction === "balance" ? "Saving…" : "Save balance"}</button>
          </form>
          <button className="text-action" disabled={busy} type="button" onClick={reportExhausted}>My network says my data is finished</button>
        </div>
      ) : (
        <p className="form-error" role="alert">Dachik could not match this tracking period to its data plan.</p>
      )}
    </section>
  );
}
