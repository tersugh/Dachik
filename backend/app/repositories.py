"""Focused database operations used by Dachik services."""

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

    def get_source(self, source_id: str) -> models.TrafficSource | None:
        return self.session.get(models.TrafficSource, source_id)

    def get_series(self, series_id: str) -> models.CounterSeries | None:
        return self.session.get(models.CounterSeries, series_id)

    def list_snapshots(self, experiment_id: str) -> list[models.ISPBalanceSnapshot]:
        return list(
            self.session.scalars(
                select(models.ISPBalanceSnapshot)
                .where(models.ISPBalanceSnapshot.experiment_id == experiment_id)
                .order_by(models.ISPBalanceSnapshot.timestamp_utc)
            )
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
