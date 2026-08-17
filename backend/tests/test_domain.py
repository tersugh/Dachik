from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app import models, schemas
from backend.app.database import Database
from backend.app.services import ConflictError, DachikService, DomainError, NotFoundError


def create_device(service: DachikService) -> models.Device:
    return service.create_device(
        schemas.DeviceCreate(
            hostname="synthetic-mac.local",
            display_name="Synthetic test Mac",
            operating_system="macOS",
            operating_system_version="test-version",
        )
    )


def create_bundle(service: DachikService) -> models.DataBundle:
    return service.create_bundle(
        schemas.DataBundleCreate(
            provider_name="Synthetic ISP",
            plan_name="Synthetic plan",
            allowance_bytes=30_000_000_000,
            billing_cycle_start=datetime(2026, 8, 1, tzinfo=UTC),
            billing_cycle_end=datetime(2026, 9, 1, tzinfo=UTC),
            timezone="Africa/Lagos",
        )
    )


def create_experiment(service: DachikService) -> models.DataAuditExperiment:
    device = create_device(service)
    bundle = create_bundle(service)
    return service.create_experiment(
        schemas.ExperimentCreate(
            data_bundle_id=bundle.id,
            device_id=device.id,
            methodology_version="test-v1",
        )
    )


def test_device_and_bundle_round_trip(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        device = create_device(service)
        bundle = create_bundle(service)

        assert service.list_devices()[0].id == device.id
        assert service.list_bundles()[0].allowance_bytes == 30_000_000_000
        assert bundle.billing_cycle_start.tzinfo is UTC


@pytest.mark.parametrize("allowance", [0, -1])
def test_bundle_rejects_non_positive_allowance(allowance: int) -> None:
    with pytest.raises(ValidationError):
        schemas.DataBundleCreate(
            provider_name="Synthetic ISP",
            plan_name="Invalid synthetic plan",
            allowance_bytes=allowance,
            billing_cycle_start=datetime(2026, 8, 1, tzinfo=UTC),
            billing_cycle_end=datetime(2026, 9, 1, tzinfo=UTC),
            timezone="UTC",
        )


def test_bundle_rejects_invalid_time_order_and_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        schemas.DataBundleCreate(
            provider_name="Synthetic ISP",
            plan_name="Invalid synthetic plan",
            allowance_bytes=1,
            billing_cycle_start=datetime(2026, 9, 1),
            billing_cycle_end=datetime(2026, 8, 1),
            timezone="Not/A_Zone",
        )


def test_experiment_state_transitions_and_foreign_keys(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment = create_experiment(service)
        assert experiment.status == "draft"

        active = service.start_experiment(experiment.id)
        assert active.status == "active"
        assert active.started_at is not None
        with pytest.raises(ConflictError):
            service.start_experiment(experiment.id)

        completed = service.complete_experiment(experiment.id)
        assert completed.status == "completed"
        assert completed.ended_at is not None
        with pytest.raises(ConflictError):
            service.complete_experiment(experiment.id)

        with pytest.raises(NotFoundError):
            service.create_experiment(
                schemas.ExperimentCreate(
                    data_bundle_id="missing",
                    device_id=experiment.device_id,
                    methodology_version="test-v1",
                )
            )

        session.add(
            models.DataAuditExperiment(
                data_bundle_id="missing",
                device_id=experiment.device_id,
                methodology_version="test-v1",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_snapshot_preserves_input_and_requires_explicit_correction(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment = create_experiment(service)
        original = service.create_snapshot(
            experiment.id,
            schemas.ISPBalanceSnapshotCreate(
                timestamp_utc=datetime(2026, 8, 2, 10, 30, tzinfo=UTC),
                reported_value="1.00",
                reported_unit="GB",
                snapshot_type="remaining_balance",
                note="Synthetic snapshot",
            ),
        )
        correction = service.create_snapshot(
            experiment.id,
            schemas.ISPBalanceSnapshotCreate(
                timestamp_utc=datetime(2026, 8, 2, 10, 31, tzinfo=UTC),
                reported_value="1.25",
                reported_unit="GB",
                snapshot_type="remaining_balance",
                correction_of_snapshot_id=original.id,
            ),
        )

        assert original.reported_value == "1.00"
        assert original.normalized_bytes == 1_000_000_000
        assert correction.correction_of_snapshot_id == original.id
        assert len(service.list_snapshots(experiment.id)) == 2

    with database.engine.begin() as connection, pytest.raises(IntegrityError, match="immutable"):
        connection.execute(
            text("UPDATE isp_balance_snapshots SET reported_value='9' WHERE id=:id"),
            {"id": original.id},
        )


@pytest.mark.parametrize("reported_value", ["-1", "NaN", "not-a-number"])
def test_snapshot_rejects_invalid_values(database: Database, reported_value: str) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment = create_experiment(service)
        with pytest.raises(DomainError):
            service.create_snapshot(
                experiment.id,
                schemas.ISPBalanceSnapshotCreate(
                    timestamp_utc=datetime.now(UTC),
                    reported_value=reported_value,
                    reported_unit="GB",
                    snapshot_type="remaining_balance",
                ),
            )


def test_counter_observation_is_idempotent_and_supports_large_bytes(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        device = create_device(service)
        source = service.create_traffic_source(
            schemas.TrafficSourceCreate(
                provider_type="synthetic-test-provider",
                domain="measured.interface",
                name="Synthetic interface source",
                scope="external interface",
            )
        )
        series = service.create_counter_series(
            schemas.CounterSeriesCreate(
                source_id=source.id,
                device_id=device.id,
                direction="download",
                identity="synthetic-en0",
                accounting_domain="measured.interface",
                scope="external interface",
            )
        )
        payload = schemas.CounterObservationCreate(
            counter_series_id=series.id,
            timestamp_utc=datetime(2026, 8, 1, 12, tzinfo=UTC),
            monotonic_timestamp_ns=9_000_000_000,
            raw_counter_bytes=9_000_000_000_000_000_000,
            session_id="synthetic-session",
            sequence_key="1",
            collector_version="test",
        )

        first, first_created = service.record_observation(payload)
        second, second_created = service.record_observation(payload)

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert second.raw_counter_bytes == 9_000_000_000_000_000_000

        changed = payload.model_copy(update={"raw_counter_bytes": 5})
        with pytest.raises(ConflictError):
            service.record_observation(changed)

        with pytest.raises(ValidationError):
            schemas.CounterObservationCreate(**(payload.model_dump() | {"raw_counter_bytes": -1}))

    with database.engine.begin() as connection, pytest.raises(IntegrityError, match="immutable"):
        connection.execute(
            text("UPDATE counter_observations SET raw_counter_bytes=1 WHERE id=:id"),
            {"id": first.id},
        )


def test_utc_type_normalizes_offsets(database: Database) -> None:
    plus_one = datetime(2026, 8, 1, 13, tzinfo=UTC) + timedelta(0)
    with database.session() as session:
        service = DachikService(session)
        bundle = service.create_bundle(
            schemas.DataBundleCreate(
                provider_name="Synthetic ISP",
                plan_name="Timezone plan",
                allowance_bytes=1,
                billing_cycle_start=plus_one,
                billing_cycle_end=plus_one + timedelta(days=1),
                timezone="UTC",
            )
        )
        bundle_id = bundle.id
    with database.session() as session:
        loaded = session.get(models.DataBundle, bundle_id)
        assert loaded is not None
        assert loaded.billing_cycle_start.tzinfo is UTC
