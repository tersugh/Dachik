"""Domain rules and transactional workflows for Dachik persistence."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from backend.app import models, schemas
from backend.app.repositories import Repository


class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


UNIT_MULTIPLIERS: dict[str, int] = {
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "KIB": 1_024,
    "MIB": 1_048_576,
    "GIB": 1_073_741_824,
}


class DachikService:
    def __init__(self, session: Session) -> None:
        self.repository = Repository(session)

    def create_device(self, data: schemas.DeviceCreate) -> models.Device:
        device = models.Device(**data.model_dump())
        self.repository.add(device)
        return device

    def list_devices(self) -> list[models.Device]:
        return self.repository.list_devices()

    def create_bundle(self, data: schemas.DataBundleCreate) -> models.DataBundle:
        bundle = models.DataBundle(**data.model_dump())
        self.repository.add(bundle)
        return bundle

    def list_bundles(self) -> list[models.DataBundle]:
        return self.repository.list_bundles()

    def create_experiment(self, data: schemas.ExperimentCreate) -> models.DataAuditExperiment:
        if self.repository.get_bundle(data.data_bundle_id) is None:
            raise NotFoundError("Data bundle not found")
        if self.repository.get_device(data.device_id) is None:
            raise NotFoundError("Device not found")
        if (
            data.measurement_source_id
            and self.repository.get_source(data.measurement_source_id) is None
        ):
            raise NotFoundError("Traffic source not found")
        experiment = models.DataAuditExperiment(**data.model_dump())
        self.repository.add(experiment)
        return experiment

    def list_experiments(self) -> list[models.DataAuditExperiment]:
        return self.repository.list_experiments()

    def get_experiment(self, experiment_id: str) -> models.DataAuditExperiment:
        experiment = self.repository.get_experiment(experiment_id)
        if experiment is None:
            raise NotFoundError("Experiment not found")
        return experiment

    def start_experiment(self, experiment_id: str) -> models.DataAuditExperiment:
        experiment = self.get_experiment(experiment_id)
        if experiment.status != models.ExperimentStatus.DRAFT.value:
            raise ConflictError("Only a draft experiment can be started")
        experiment.status = models.ExperimentStatus.ACTIVE.value
        experiment.started_at = datetime.now(UTC)
        return experiment

    def complete_experiment(self, experiment_id: str) -> models.DataAuditExperiment:
        experiment = self.get_experiment(experiment_id)
        if experiment.status != models.ExperimentStatus.ACTIVE.value:
            raise ConflictError("Only an active experiment can be completed")
        experiment.status = models.ExperimentStatus.COMPLETED.value
        experiment.ended_at = datetime.now(UTC)
        return experiment

    def create_snapshot(
        self, experiment_id: str, data: schemas.ISPBalanceSnapshotCreate
    ) -> models.ISPBalanceSnapshot:
        self.get_experiment(experiment_id)
        normalized_bytes = self._normalize_bytes(data.reported_value, data.reported_unit)
        if data.correction_of_snapshot_id:
            original = self.repository.get_snapshot(data.correction_of_snapshot_id)
            if original is None or original.experiment_id != experiment_id:
                raise NotFoundError("Corrected snapshot not found in this experiment")
        snapshot = models.ISPBalanceSnapshot(
            experiment_id=experiment_id,
            normalized_bytes=normalized_bytes,
            **data.model_dump(),
        )
        self.repository.add(snapshot)
        return snapshot

    def list_snapshots(self, experiment_id: str) -> list[models.ISPBalanceSnapshot]:
        self.get_experiment(experiment_id)
        return self.repository.list_snapshots(experiment_id)

    def create_traffic_source(self, data: schemas.TrafficSourceCreate) -> models.TrafficSource:
        source = models.TrafficSource(**data.model_dump())
        self.repository.add(source)
        return source

    def create_counter_series(self, data: schemas.CounterSeriesCreate) -> models.CounterSeries:
        if self.repository.get_source(data.source_id) is None:
            raise NotFoundError("Traffic source not found")
        if self.repository.get_device(data.device_id) is None:
            raise NotFoundError("Device not found")
        series = models.CounterSeries(**data.model_dump())
        self.repository.add(series)
        return series

    def record_observation(
        self, data: schemas.CounterObservationCreate
    ) -> tuple[models.CounterObservation, bool]:
        if self.repository.get_series(data.counter_series_id) is None:
            raise NotFoundError("Counter series not found")
        candidate = models.CounterObservation(**data.model_dump())
        observation, created = self.repository.insert_observation_idempotently(candidate)
        if not created and any(
            (
                observation.timestamp_utc != data.timestamp_utc.astimezone(UTC),
                observation.monotonic_timestamp_ns != data.monotonic_timestamp_ns,
                observation.raw_counter_bytes != data.raw_counter_bytes,
                observation.collector_version != data.collector_version,
            )
        ):
            raise ConflictError("Idempotency key already exists with different observation data")
        return observation, created

    @staticmethod
    def _normalize_bytes(reported_value: str, reported_unit: str) -> int | None:
        try:
            value = Decimal(reported_value)
        except InvalidOperation as exc:
            raise DomainError("reported_value must be a decimal number") from exc
        if not value.is_finite() or value < 0:
            raise DomainError("reported_value must be a finite non-negative number")
        multiplier = UNIT_MULTIPLIERS.get(reported_unit.strip().upper())
        if multiplier is None:
            return None
        normalized = value * multiplier
        if normalized != normalized.to_integral_value():
            return None
        return int(normalized)
