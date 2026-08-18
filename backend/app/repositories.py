"""Focused database operations used by Dachik services."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app import models


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: models.Base) -> None:
        self.session.add(entity)
        self.session.flush()

    def list_devices(self) -> list[models.Device]:
        return list(self.session.scalars(select(models.Device).order_by(models.Device.created_at)))

    def get_device(self, device_id: str) -> models.Device | None:
        return self.session.get(models.Device, device_id)

    def list_bundles(self) -> list[models.DataBundle]:
        return list(
            self.session.scalars(select(models.DataBundle).order_by(models.DataBundle.created_at))
        )

    def get_bundle(self, bundle_id: str) -> models.DataBundle | None:
        return self.session.get(models.DataBundle, bundle_id)

    def list_experiments(self) -> list[models.DataAuditExperiment]:
        return list(
            self.session.scalars(
                select(models.DataAuditExperiment).order_by(
                    models.DataAuditExperiment.created_at.desc()
                )
            )
        )

    def get_experiment(self, experiment_id: str) -> models.DataAuditExperiment | None:
        return self.session.get(models.DataAuditExperiment, experiment_id)

    def get_current_tracking_target(self) -> models.CurrentTrackingTarget | None:
        return self.session.get(models.CurrentTrackingTarget, 1)

    def select_tracking_target(self, experiment_id: str) -> models.CurrentTrackingTarget:
        target = self.get_current_tracking_target()
        if target is None:
            target = models.CurrentTrackingTarget(id=1, experiment_id=experiment_id)
            self.add(target)
        else:
            target.experiment_id = experiment_id
            target.selected_at = models.utc_now()
        return target

    def clear_tracking_target(self, experiment_id: str) -> None:
        target = self.get_current_tracking_target()
        if target is not None and target.experiment_id == experiment_id:
            self.session.delete(target)
            self.session.flush()

    def get_source(self, source_id: str) -> models.TrafficSource | None:
        return self.session.get(models.TrafficSource, source_id)

    def get_series(self, series_id: str) -> models.CounterSeries | None:
        return self.session.get(models.CounterSeries, series_id)

    def find_source(self, provider_type: str, name: str, scope: str) -> models.TrafficSource | None:
        return self.session.scalar(
            select(models.TrafficSource).where(
                models.TrafficSource.provider_type == provider_type,
                models.TrafficSource.name == name,
                models.TrafficSource.scope == scope,
            )
        )

    def find_series(
        self, source_id: str, device_id: str, direction: str, identity: str, scope: str
    ) -> models.CounterSeries | None:
        return self.session.scalar(
            select(models.CounterSeries).where(
                models.CounterSeries.source_id == source_id,
                models.CounterSeries.device_id == device_id,
                models.CounterSeries.direction == direction,
                models.CounterSeries.identity == identity,
                models.CounterSeries.accounting_domain == "measured.interface",
                models.CounterSeries.scope == scope,
            )
        )

    def previous_observation(
        self, series_id: str, timestamp: datetime
    ) -> models.CounterObservation | None:
        return self.session.scalar(
            select(models.CounterObservation)
            .where(
                models.CounterObservation.counter_series_id == series_id,
                models.CounterObservation.timestamp_utc < timestamp,
            )
            .order_by(models.CounterObservation.timestamp_utc.desc())
            .limit(1)
        )

    def latest_observation_for_device(self, device_id: str) -> models.CounterObservation | None:
        return self.session.scalar(
            select(models.CounterObservation)
            .join(models.CounterSeries)
            .where(
                models.CounterSeries.device_id == device_id,
                models.CounterSeries.accounting_domain == "measured.interface",
            )
            .order_by(models.CounterObservation.timestamp_utc.desc())
            .limit(1)
        )

    def interface_series_for_device(self, device_id: str) -> list[models.CounterSeries]:
        return list(
            self.session.scalars(
                select(models.CounterSeries).where(
                    models.CounterSeries.device_id == device_id,
                    models.CounterSeries.accounting_domain == "measured.interface",
                )
            )
        )

    def interface_series_for_source(
        self, device_id: str, source_id: str | None
    ) -> list[models.CounterSeries]:
        if source_id is None:
            return []
        return list(
            self.session.scalars(
                select(models.CounterSeries).where(
                    models.CounterSeries.device_id == device_id,
                    models.CounterSeries.source_id == source_id,
                    models.CounterSeries.accounting_domain == "measured.interface",
                )
            )
        )

    def latest_observation_for_source(
        self, source_id: str | None
    ) -> models.CounterObservation | None:
        if source_id is None:
            return None
        return self.session.scalar(
            select(models.CounterObservation)
            .join(models.CounterSeries)
            .where(models.CounterSeries.source_id == source_id)
            .order_by(models.CounterObservation.timestamp_utc.desc())
            .limit(1)
        )

    def usage_intervals(
        self, series_ids: list[str], start: datetime, end: datetime
    ) -> list[models.UsageInterval]:
        if not series_ids:
            return []
        return list(
            self.session.scalars(
                select(models.UsageInterval).where(
                    models.UsageInterval.counter_series_id.in_(series_ids),
                    models.UsageInterval.start_timestamp >= start,
                    models.UsageInterval.end_timestamp <= end,
                    models.UsageInterval.quality == "accepted",
                )
            )
        )

    def discontinuities(
        self, experiment_id: str, start: datetime, end: datetime
    ) -> list[models.MeasurementDiscontinuity]:
        return list(
            self.session.scalars(
                select(models.MeasurementDiscontinuity).where(
                    models.MeasurementDiscontinuity.experiment_id == experiment_id,
                    models.MeasurementDiscontinuity.start_timestamp < end,
                    models.MeasurementDiscontinuity.end_timestamp > start,
                )
            )
        )

    def latest_collector_run(self) -> models.CollectorRun | None:
        return self.session.scalar(
            select(models.CollectorRun).order_by(models.CollectorRun.started_at.desc()).limit(1)
        )

    def list_snapshots(self, experiment_id: str) -> list[models.ISPBalanceSnapshot]:
        return list(
            self.session.scalars(
                select(models.ISPBalanceSnapshot)
                .where(models.ISPBalanceSnapshot.experiment_id == experiment_id)
                .order_by(models.ISPBalanceSnapshot.timestamp_utc)
            )
        )

    def latest_remaining_balance(
        self, experiment_id: str, as_of: datetime
    ) -> models.ISPBalanceSnapshot | None:
        return self.session.scalar(
            select(models.ISPBalanceSnapshot)
            .where(
                models.ISPBalanceSnapshot.experiment_id == experiment_id,
                models.ISPBalanceSnapshot.snapshot_type == "remaining_balance",
                models.ISPBalanceSnapshot.normalized_bytes.is_not(None),
                models.ISPBalanceSnapshot.timestamp_utc <= as_of,
            )
            .order_by(models.ISPBalanceSnapshot.timestamp_utc.desc())
            .limit(1)
        )

    def initial_remaining_balance(
        self, experiment_id: str
    ) -> models.ISPBalanceSnapshot | None:
        """Return the first remaining-balance evidence recorded for tracking.

        Creation order is intentional: a later entry may describe an earlier
        provider check, but it must not retroactively replace the immutable
        tracking baseline.
        """
        return self.session.scalar(
            select(models.ISPBalanceSnapshot)
            .where(
                models.ISPBalanceSnapshot.experiment_id == experiment_id,
                models.ISPBalanceSnapshot.snapshot_type == "remaining_balance",
                models.ISPBalanceSnapshot.normalized_bytes.is_not(None),
            )
            .order_by(
                models.ISPBalanceSnapshot.created_at,
                models.ISPBalanceSnapshot.id,
            )
            .limit(1)
        )

    def get_snapshot(self, snapshot_id: str) -> models.ISPBalanceSnapshot | None:
        return self.session.get(models.ISPBalanceSnapshot, snapshot_id)

    def insert_observation_idempotently(
        self, observation: models.CounterObservation
    ) -> tuple[models.CounterObservation, bool]:
        try:
            with self.session.begin_nested():
                self.session.add(observation)
                self.session.flush()
            return observation, True
        except IntegrityError:
            existing = self.session.scalar(
                select(models.CounterObservation).where(
                    models.CounterObservation.counter_series_id == observation.counter_series_id,
                    models.CounterObservation.session_id == observation.session_id,
                    models.CounterObservation.sequence_key == observation.sequence_key,
                )
            )
            if existing is None:
                raise
            return existing, False
