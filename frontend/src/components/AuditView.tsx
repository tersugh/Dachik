import { useEffect, useState } from "react";

import { type AuditState, type DachikApi } from "../api/client";
import { formatObservedBytes } from "../domain/bundleSize";
import { formatAuditDay, formatAuditTime, formatAuditTimestamp } from "../domain/dateTime";

interface AuditViewProps {
  api: DachikApi;
  onClose: () => void;
}

function duration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

export function AuditView({ api, onClose }: AuditViewProps) {
  const [audit, setAudit] = useState<AuditState | null>(null);
  const [history, setHistory] = useState<Awaited<ReturnType<DachikApi["listAudits"]>>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    void Promise.all([api.getCurrentAudit(), api.listAudits()])
      .then(([current, items]) => {
        if (mounted) {
          setAudit(current);
          setHistory(items);
        }
      })
      .catch((reason: unknown) => {
        if (mounted) setError(reason instanceof Error ? reason.message : "Dachik could not load the audit");
      });
    return () => {
      mounted = false;
    };
  }, [api]);

  async function openAudit(id: string) {
    try {
      setAudit(await api.getAudit(id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dachik could not load that audit");
    }
  }

  async function download(format: "pdf" | "csv" | "json") {
    if (!audit) return;
    try {
      const blob = await api.downloadAudit(audit.audit_id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `dachik-audit.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dachik could not download the audit");
    }
  }

  if (!audit) {
    return <section className="audit-view"><button type="button" onClick={onClose}>Back</button><p>{error ?? "Loading your audit…"}</p></section>;
  }

  const highestHours = [...audit.hourly]
    .filter((item) => item.total_observed_bytes > 0)
    .sort((left, right) => right.total_observed_bytes - left.total_observed_bytes)
    .slice(0, 3);
  const highestDays = [...audit.daily]
    .filter((item) => item.total_observed_bytes > 0)
    .sort((left, right) => right.total_observed_bytes - left.total_observed_bytes)
    .slice(0, 3);

  return (
    <section className="audit-view" aria-labelledby="audit-heading">
      <button className="text-action" type="button" onClick={onClose}>Back to current plan</button>
      {error && <p className="form-error" role="alert">{error}</p>}
      <header className="audit-header">
        <p className="eyebrow">Your data audit</p>
        <h2 id="audit-heading">{audit.provider_name}</h2>
        <p>{audit.plan_name}</p>
        <span className="quality-pill">{audit.audit_status === "final" ? "Final" : "In progress"}</span>
        <p>Times shown in {audit.timezone}</p>
      </header>
      <dl className="audit-summary">
        <div><dt>Audit started</dt><dd>{formatAuditTimestamp(audit.audit_start, audit.timezone)}</dd></div>
        <div><dt>Starting network balance</dt><dd>{audit.initial_tracking_balance_bytes === null ? "Unknown" : formatObservedBytes(audit.initial_tracking_balance_bytes)}</dd></div>
        <div><dt>Dachik observed</dt><dd>{formatObservedBytes(audit.total_observed_bytes)}</dd></div>
        <div><dt>Dachik-accounted remainder</dt><dd>{audit.accounted_remainder_bytes === null ? "Unknown" : formatObservedBytes(audit.accounted_remainder_bytes)}</dd></div>
        <div><dt>Latest network-reported balance</dt><dd>{audit.latest_provider_balance_bytes === null ? "Unknown" : formatObservedBytes(audit.latest_provider_balance_bytes)}</dd></div>
        <div><dt>Measurement quality</dt><dd>{audit.evidence_quality[0]?.toUpperCase()}{audit.evidence_quality.slice(1)} · {audit.evidence_coverage_percent}%</dd></div>
        <div><dt>Last measurement</dt><dd>{audit.latest_trusted_observation ? formatAuditTimestamp(audit.latest_trusted_observation, audit.timezone) : "None yet"}</dd></div>
      </dl>
      {audit.usage_exceeds_starting_balance && <p className="coverage-warning">Dachik has observed usage beyond the balance reported when tracking began.</p>}
      {audit.comparisons.at(-1) && <section className="panel"><h3>Latest network comparison</h3><p>{audit.comparisons.at(-1)?.conclusion}</p><p>Network deduction: {formatObservedBytes(audit.comparisons.at(-1)!.provider_deduction_bytes)} · Dachik: {formatObservedBytes(audit.comparisons.at(-1)!.dachik_usage_bytes)} · Difference: {formatObservedBytes(audit.comparisons.at(-1)!.observed_difference_bytes)}</p></section>}
      {(highestHours.length > 0 || highestDays.length > 0) && <section className="audit-section"><h3>Highest usage</h3>{highestHours.map((hour) => <article className="ledger-row" key={`high-${hour.start}`}><strong>{formatAuditTime(hour.start, audit.timezone)}–{formatAuditTime(hour.end, audit.timezone)}</strong><span>{formatObservedBytes(hour.total_observed_bytes)}</span></article>)}{highestDays.map((day) => <article className="ledger-row" key={`high-${day.start}`}><strong>{formatAuditDay(day.start, audit.timezone)}</strong><span>{formatObservedBytes(day.total_observed_bytes)}</span></article>)}</section>}
      <section className="audit-section"><h3>Daily breakdown</h3>{audit.daily.map((day) => <article className="ledger-row" key={day.start}><strong>{formatAuditDay(day.start, audit.timezone)}</strong><span>{formatObservedBytes(day.total_observed_bytes)} observed · {formatObservedBytes(day.observed_rx_bytes)} down · {formatObservedBytes(day.observed_tx_bytes)} up</span><span>{duration(day.measured_duration_seconds)} measured · {duration(day.known_inactive_duration_seconds)} different connection · {duration(day.unknown_duration_seconds)} unknown</span><span>Accounted remainder: {day.ending_accounted_remainder_bytes === null ? "Unknown" : formatObservedBytes(day.ending_accounted_remainder_bytes)}</span></article>)}</section>
      <section className="audit-section"><h3>Hourly ledger</h3>{audit.hourly.map((hour) => <article className="ledger-row" key={hour.start}><strong>{formatAuditTime(hour.start, audit.timezone)}–{formatAuditTime(hour.end, audit.timezone)}</strong><span>{hour.state === "unknown" ? "Measurement unavailable · usage unknown" : hour.state === "known_inactive" ? "Different connection · not attributed" : `${formatObservedBytes(hour.total_observed_bytes)} observed`}</span></article>)}</section>
      <section className="audit-section"><h3>Important events</h3>{audit.events.map((event) => <article className="ledger-row" key={`${event.timestamp}-${event.event_type}`}><strong>{formatAuditTimestamp(event.timestamp, audit.timezone, { includeSeconds: true })}</strong><span>{event.description}</span>{event.reported_balance_bytes !== null && <span>Network reported {formatObservedBytes(event.reported_balance_bytes)} remaining{event.accounted_remainder_bytes === null ? "" : ` · Dachik accounted ${formatObservedBytes(event.accounted_remainder_bytes)}`}</span>}</article>)}</section>
      <div className="download-actions"><button type="button" onClick={() => void download("pdf")}>Download audit</button><button className="secondary" type="button" onClick={() => void download("csv")}>CSV</button><button className="secondary" type="button" onClick={() => void download("json")}>JSON</button></div>
      <section className="audit-section"><h3>Past audits</h3>{history.filter((item) => item.audit_id !== audit.audit_id).map((item) => <button className="history-row" key={item.audit_id} type="button" onClick={() => void openAudit(item.audit_id)}>{item.provider_name} · {formatObservedBytes(item.allowance_bytes)} · {formatAuditDay(item.bundle_expiry, item.timezone)}</button>)}</section>
    </section>
  );
}
