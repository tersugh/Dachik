"""Deterministic continuous-audit derivation from immutable measurement evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from backend.app import models, schemas
from backend.app.repositories import Repository
from backend.app.services import NotFoundError


@dataclass(frozen=True, slots=True)
class TrustedPair:
    start: datetime
    end: datetime
    rx_bytes: int
    tx_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.rx_bytes + self.tx_bytes


class AuditEngine:
    """One authoritative arithmetic path for API, UI, and every export."""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def build(
        self,
        experiment_id: str,
        *,
        as_of: datetime | None = None,
        sensor_status: str = "unknown",
    ) -> schemas.AuditState:
        experiment = self.repository.get_experiment(experiment_id)
        if experiment is None or experiment.started_at is None:
            raise NotFoundError("Audit not found")
        bundle = self.repository.get_bundle(experiment.data_bundle_id)
        if bundle is None:
            raise NotFoundError("Data plan not found")
        requested = (as_of or datetime.now(UTC)).astimezone(UTC)
        audit_start = max(experiment.started_at, bundle.billing_cycle_start)
        audit_end = min(
            requested,
            experiment.ended_at or requested,
            bundle.billing_cycle_end,
        )
        audit_end = max(audit_start, audit_end)
        pairs = self._trusted_pairs(experiment, audit_start, audit_end)
        discontinuities = self.repository.discontinuities(
            experiment.id, audit_start, audit_end
        )
        snapshots = [
            item
            for item in self.repository.list_snapshots(experiment.id)
            if item.timestamp_utc <= audit_end
        ]
        measured_ranges = [(item.start, item.end) for item in pairs]
        known_ranges = [
            (max(item.start_timestamp, audit_start), min(item.end_timestamp, audit_end))
            for item in discontinuities
            if item.reason == "connection_changed"
        ]
        measured_seconds = self._union_seconds(measured_ranges)
        known_seconds = self._union_seconds(known_ranges)
        eligible_seconds = max(0, int((audit_end - audit_start).total_seconds()))
        known_union_seconds = self._union_seconds(measured_ranges + known_ranges)
        unknown_seconds = max(0, eligible_seconds - known_union_seconds)
        coverage = self._coverage(measured_seconds, unknown_seconds)
        quality = self._quality(coverage)
        rx = sum(item.rx_bytes for item in pairs)
        tx = sum(item.tx_bytes for item in pairs)
        total = rx + tx
        baseline_snapshot = self.repository.initial_remaining_balance(experiment.id)
        baseline = baseline_snapshot.normalized_bytes if baseline_snapshot else None
        remainder = baseline - total if baseline is not None else None
        remaining_snapshots = [
            item
            for item in snapshots
            if item.snapshot_type == "remaining_balance" and item.normalized_bytes is not None
        ]
        latest_balance = remaining_snapshots[-1].normalized_bytes if remaining_snapshots else None
        timezone = ZoneInfo(bundle.timezone)
        daily = self._buckets(
            pairs, known_ranges, audit_start, audit_end, timezone, "day", baseline
        )
        hourly = self._buckets(
            pairs, known_ranges, audit_start, audit_end, timezone, "hour", baseline
        )
        checkpoints = [
            schemas.AuditSnapshotCheckpoint(
                timestamp=item.timestamp_utc,
                reported_value=item.reported_value,
                reported_unit=item.reported_unit,
                normalized_bytes=item.normalized_bytes,
                accounted_remainder_bytes=self._remainder_at(
                    baseline, pairs, item.timestamp_utc
                ),
                note=item.note,
            )
            for item in snapshots
        ]
        events = self._events(discontinuities, checkpoints)
        comparisons = self._comparisons(
            remaining_snapshots, pairs, known_ranges, discontinuities
        )
        latest_observation = max((item.end for item in pairs), default=None)
        final = audit_end >= bundle.billing_cycle_end or experiment.status == "completed"
        return schemas.AuditState(
            audit_id=experiment.id,
            provider_name=bundle.provider_name,
            plan_name=bundle.plan_name,
            original_allowance_bytes=bundle.allowance_bytes,
            bundle_start=bundle.billing_cycle_start,
            bundle_expiry=bundle.billing_cycle_end,
            timezone=bundle.timezone,
            audit_status="final" if final else "in_progress",
            audit_start=audit_start,
            as_of_timestamp=audit_end,
            initial_tracking_balance_bytes=baseline,
            latest_provider_balance_bytes=latest_balance,
            observed_rx_bytes=rx,
            observed_tx_bytes=tx,
            total_observed_bytes=total,
            accounted_remainder_bytes=remainder,
            usage_exceeds_starting_balance=remainder is not None and remainder < 0,
            latest_trusted_observation=latest_observation,
            sensor_status=sensor_status,
            measured_duration_seconds=measured_seconds,
            known_inactive_duration_seconds=known_seconds,
            unknown_duration_seconds=unknown_seconds,
            evidence_coverage_percent=coverage,
            evidence_quality=quality,
            has_unknown_gaps=unknown_seconds > 0,
            daily=daily,
            hourly=hourly,
            events=events,
            isp_checkpoints=checkpoints,
            comparisons=comparisons,
            methodology_version=experiment.methodology_version,
            measurement_boundary=experiment.measurement_boundary,
            limitations=[
                "Dachik measures this Mac, not every device using the data plan.",
                "Unknown periods are not treated as zero usage.",
                "Interface counters may differ from provider accounting boundaries.",
            ],
        )

    def _trusted_pairs(
        self,
        experiment: models.DataAuditExperiment,
        start: datetime,
        end: datetime,
    ) -> list[TrustedPair]:
        series = self.repository.interface_series_for_source(
            experiment.device_id, experiment.measurement_source_id
        )
        by_id = {item.id: item for item in series}
        intervals = self.repository.usage_intervals(list(by_id), start, end)
        grouped: dict[tuple[datetime, datetime], dict[str, int]] = {}
        duplicate_keys: set[tuple[datetime, datetime]] = set()
        for interval in intervals:
            direction = by_id[interval.counter_series_id].direction
            key = (interval.start_timestamp, interval.end_timestamp)
            values = grouped.setdefault(key, {})
            if direction in values:
                duplicate_keys.add(key)
            values[direction] = interval.delta_bytes
        pairs = [
            TrustedPair(key[0], key[1], values["download"], values["upload"])
            for key, values in grouped.items()
            if key not in duplicate_keys and {"download", "upload"} <= values.keys()
        ]
        pairs.sort(key=lambda item: item.start)
        overlapping: set[int] = set()
        for index, (previous, current) in enumerate(zip(pairs, pairs[1:], strict=False)):
            if current.start < previous.end:
                overlapping.update((index, index + 1))
        return [item for index, item in enumerate(pairs) if index not in overlapping]

    def _buckets(
        self,
        pairs: list[TrustedPair],
        known_ranges: list[tuple[datetime, datetime]],
        start: datetime,
        end: datetime,
        timezone: ZoneInfo,
        unit: str,
        baseline: int | None,
    ) -> list[schemas.AuditBucket]:
        boundaries = self._bucket_boundaries(start, end, timezone, unit)
        result: list[schemas.AuditBucket] = []
        cumulative = sum(item.total_bytes for item in pairs if item.end <= boundaries[0])
        for bucket_start, bucket_end in zip(boundaries, boundaries[1:], strict=False):
            assigned = [
                item for item in pairs if bucket_start < item.end <= bucket_end
            ]
            measured = [
                (max(item.start, bucket_start), min(item.end, bucket_end))
                for item in pairs
                if item.start < bucket_end and item.end > bucket_start
            ]
            known = [
                (max(item_start, bucket_start), min(item_end, bucket_end))
                for item_start, item_end in known_ranges
                if item_start < bucket_end and item_end > bucket_start
            ]
            measured_seconds = self._union_seconds(measured)
            known_seconds = self._union_seconds(known)
            eligible = max(0, int((bucket_end - bucket_start).total_seconds()))
            unknown = max(0, eligible - self._union_seconds(measured + known))
            rx = sum(item.rx_bytes for item in assigned)
            tx = sum(item.tx_bytes for item in assigned)
            total = rx + tx
            boundary_bytes = sum(
                item.total_bytes for item in assigned if item.start < bucket_start
            )
            starting_remainder = baseline - cumulative if baseline is not None else None
            cumulative += total
            ending_remainder = baseline - cumulative if baseline is not None else None
            states = sum(value > 0 for value in (measured_seconds, known_seconds, unknown))
            state: Literal["measured", "known_inactive", "unknown", "mixed"] = (
                "mixed"
                if states > 1
                else "measured"
                if measured_seconds
                else "known_inactive"
                if known_seconds
                else "unknown"
            )
            result.append(
                schemas.AuditBucket(
                    start=bucket_start,
                    end=bucket_end,
                    observed_rx_bytes=rx,
                    observed_tx_bytes=tx,
                    total_observed_bytes=total,
                    starting_accounted_remainder_bytes=starting_remainder,
                    ending_accounted_remainder_bytes=ending_remainder,
                    measured_duration_seconds=measured_seconds,
                    known_inactive_duration_seconds=known_seconds,
                    unknown_duration_seconds=unknown,
                    boundary_spanning_bytes=boundary_bytes,
                    state=state,
                )
            )
        return result

    @staticmethod
    def _bucket_boundaries(
        start: datetime, end: datetime, timezone: ZoneInfo, unit: str
    ) -> list[datetime]:
        local_start = start.astimezone(timezone)
        if unit == "day":
            cursor = datetime.combine(local_start.date(), time.min, timezone)
            step = timedelta(days=1)
        else:
            cursor = local_start.replace(minute=0, second=0, microsecond=0)
            step = timedelta(hours=1)
        boundaries = [start]
        cursor += step
        while cursor.astimezone(UTC) < end:
            boundaries.append(cursor.astimezone(UTC))
            cursor += step
        boundaries.append(end)
        return sorted(set(boundaries))

    def _comparisons(
        self,
        snapshots: list[models.ISPBalanceSnapshot],
        pairs: list[TrustedPair],
        known_ranges: list[tuple[datetime, datetime]],
        discontinuities: list[models.MeasurementDiscontinuity],
    ) -> list[schemas.ISPComparisonWindow]:
        result: list[schemas.ISPComparisonWindow] = []
        for first, last in zip(snapshots, snapshots[1:], strict=False):
            assert first.normalized_bytes is not None and last.normalized_bytes is not None
            deduction = first.normalized_bytes - last.normalized_bytes
            if deduction < 0 or last.timestamp_utc <= first.timestamp_utc:
                continue
            selected = [
                item
                for item in pairs
                if item.start >= first.timestamp_utc and item.end <= last.timestamp_utc
            ]
            measured = [(item.start, item.end) for item in selected]
            known = [
                (max(start, first.timestamp_utc), min(end, last.timestamp_utc))
                for start, end in known_ranges
                if start < last.timestamp_utc and end > first.timestamp_utc
            ]
            eligible = int((last.timestamp_utc - first.timestamp_utc).total_seconds())
            measured_seconds = self._union_seconds(measured)
            known_seconds = self._union_seconds(known)
            unknown = max(0, eligible - self._union_seconds(measured + known))
            coverage = round((eligible - unknown) / eligible * 100, 1) if eligible else 0.0
            quality = self._quality(coverage)
            usage = sum(item.total_bytes for item in selected)
            difference = deduction - usage
            threshold = max(1_000_000, deduction // 20)
            if quality == "insufficient":
                conclusion = "Dachik does not have enough evidence to make a reliable comparison."
            elif abs(difference) <= threshold:
                conclusion = "Accounting closely agrees."
            elif last.normalized_bytes == 0:
                conclusion = "Possible accounting discrepancy worth reviewing."
            else:
                conclusion = "A difference was observed."
            result.append(
                schemas.ISPComparisonWindow(
                    start_timestamp=first.timestamp_utc,
                    end_timestamp=last.timestamp_utc,
                    start_balance_bytes=first.normalized_bytes,
                    end_balance_bytes=last.normalized_bytes,
                    provider_deduction_bytes=deduction,
                    dachik_usage_bytes=usage,
                    observed_difference_bytes=difference,
                    measured_duration_seconds=measured_seconds,
                    known_inactive_duration_seconds=known_seconds,
                    unknown_duration_seconds=unknown,
                    evidence_coverage_percent=coverage,
                    evidence_quality=quality,
                    conclusion=conclusion,
                )
            )
        return result

    def _events(
        self,
        discontinuities: list[models.MeasurementDiscontinuity],
        checkpoints: list[schemas.AuditSnapshotCheckpoint],
    ) -> list[schemas.AuditEvent]:
        events: list[schemas.AuditEvent] = []
        for item in discontinuities:
            changed = item.reason == "connection_changed"
            events.append(
                schemas.AuditEvent(
                    timestamp=item.start_timestamp,
                    event_type="connection_changed" if changed else "measurement_interrupted",
                    description=(
                        "Audited connection changed."
                        if changed
                        else "Measurement continuity was interrupted."
                    ),
                )
            )
            events.append(
                schemas.AuditEvent(
                    timestamp=item.end_timestamp,
                    event_type="measurement_resumed",
                    description="Trusted measurement resumed with a new baseline.",
                )
            )
        for checkpoint in checkpoints:
            events.append(
                schemas.AuditEvent(
                    timestamp=checkpoint.timestamp,
                    event_type="network_balance_updated",
                    description="Network balance was updated.",
                    reported_balance_bytes=checkpoint.normalized_bytes,
                    accounted_remainder_bytes=checkpoint.accounted_remainder_bytes,
                )
            )
        return sorted(events, key=lambda item: item.timestamp)

    @staticmethod
    def _remainder_at(
        baseline: int | None, pairs: list[TrustedPair], timestamp: datetime
    ) -> int | None:
        if baseline is None:
            return None
        return baseline - sum(item.total_bytes for item in pairs if item.end <= timestamp)

    @staticmethod
    def _quality(coverage: float) -> schemas.EvidenceQuality:
        if coverage >= 95:
            return "excellent"
        if coverage >= 85:
            return "good"
        if coverage >= 60:
            return "limited"
        return "insufficient"

    @staticmethod
    def _coverage(measured_seconds: int, unknown_seconds: int) -> float:
        quality_relevant_seconds = measured_seconds + unknown_seconds
        if quality_relevant_seconds == 0:
            return 0.0
        return round(measured_seconds / quality_relevant_seconds * 100, 1)

    @staticmethod
    def _union_seconds(ranges: list[tuple[datetime, datetime]]) -> int:
        valid = sorted((start, end) for start, end in ranges if end > start)
        if not valid:
            return 0
        total = timedelta()
        current_start, current_end = valid[0]
        for start, end in valid[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                total += current_end - current_start
                current_start, current_end = start, end
        total += current_end - current_start
        return int(total.total_seconds())
