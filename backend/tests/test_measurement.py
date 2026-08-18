from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.app import models, schemas
from backend.app.database import Database
from backend.app.services import (
    ConflictError,
    ConnectionAttributionError,
    DachikService,
    MultipleActivePlansError,
    SensorLifecycleState,
)

BASE = datetime(2026, 8, 17, 12, tzinfo=UTC)


def setup_tracking(
    service: DachikService, *, connection_fingerprint: str | None = "audited-connection"
) -> tuple[models.DataAuditExperiment, models.CounterSeries, models.CounterSeries]:
    device = service.create_device(
        schemas.DeviceCreate(
            hostname="measurement-test-mac",
            display_name="Measurement test Mac",
            operating_system="macOS",
        )
    )
    bundle = service.create_bundle(
        schemas.DataBundleCreate(
            provider_name="Synthetic network",
            plan_name="Measurement test plan",
            allowance_bytes=30_000_000_000,
            billing_cycle_start=BASE - timedelta(days=1),
            billing_cycle_end=BASE + timedelta(days=30),
            timezone="UTC",
        )
    )
    experiment = service.create_experiment(
        schemas.ExperimentCreate(
            data_bundle_id=bundle.id,
            device_id=device.id,
            methodology_version="test-v1",
        )
    )
    service.start_experiment(experiment.id)
    experiment.started_at = BASE - timedelta(seconds=1)
    _, download, upload = service.ensure_interface_setup(
        "en0", "test-provider", connection_fingerprint
    )
    return experiment, download, upload


def pair(
    download: models.CounterSeries,
    upload: models.CounterSeries,
    *,
    at: datetime,
    rx: int,
    tx: int,
    sequence: str,
    session: str = "boot-1/run-1",
) -> schemas.InterfaceObservationCreate:
    monotonic_ns = int((at - BASE).total_seconds() * 1_000_000_000) + 10_000_000_000
    return schemas.InterfaceObservationCreate(
        download=schemas.CounterObservationCreate(
            counter_series_id=download.id,
            timestamp_utc=at,
            monotonic_timestamp_ns=monotonic_ns,
            raw_counter_bytes=rx,
            session_id=session,
            sequence_key=sequence,
            collector_version="test",
        ),
        upload=schemas.CounterObservationCreate(
            counter_series_id=upload.id,
            timestamp_utc=at,
            monotonic_timestamp_ns=monotonic_ns,
            raw_counter_bytes=tx,
            session_id=session,
            sequence_key=sequence,
            collector_version="test",
        ),
    )


def intervals(service: DachikService) -> list[models.UsageInterval]:
    return list(service.repository.session.scalars(select(models.UsageInterval)))


def discontinuities(service: DachikService) -> list[models.MeasurementDiscontinuity]:
    return list(service.repository.session.scalars(select(models.MeasurementDiscontinuity)))


def record_remaining_balance(
    service: DachikService,
    experiment_id: str,
    value: str,
    *,
    timestamp: datetime = BASE,
) -> models.ISPBalanceSnapshot:
    return service.create_snapshot(
        experiment_id,
        schemas.ISPBalanceSnapshotCreate(
            timestamp_utc=timestamp,
            reported_value=value,
            reported_unit="GB",
            snapshot_type="remaining_balance",
            provenance="manual",
        ),
    )


def record_usage(
    service: DachikService,
    download: models.CounterSeries,
    upload: models.CounterSeries,
    *,
    rx_delta: int,
    tx_delta: int,
) -> None:
    service.record_interface_observation(
        pair(download, upload, at=BASE, rx=10_000, tx=5_000, sequence="baseline"),
        max_gap=timedelta(seconds=30),
    )
    service.record_interface_observation(
        pair(
            download,
            upload,
            at=BASE + timedelta(seconds=10),
            rx=10_000 + rx_delta,
            tx=5_000 + tx_delta,
            sequence="measured",
        ),
        max_gap=timedelta(seconds=30),
    )


def test_monotonic_pair_derives_exact_rx_tx_intervals(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(download, upload, at=BASE + timedelta(seconds=10), rx=1_600, tx=800, sequence="2"),
            max_gap=timedelta(seconds=30),
        )

        values = sorted(item.delta_bytes for item in intervals(service))
        assert values == [300, 600]
        assert sum(values) == 900


@pytest.mark.parametrize(
    ("first", "second"),
    [((5_000, 1_000), (100, 50)), ((1_000, 1_000), (1_500, 50))],
)
def test_any_counter_reset_rejects_entire_pair(
    database: Database, first: tuple[int, int], second: tuple[int, int]
) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=first[0], tx=first[1], sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=10),
                rx=second[0],
                tx=second[1],
                sequence="2",
            ),
            max_gap=timedelta(seconds=30),
        )

        assert intervals(service) == []
        assert [item.reason for item in discontinuities(service)] == ["counter_reset"]


def test_restart_and_measurement_gap_create_no_usage(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=10),
                rx=1_500,
                tx=700,
                sequence="1",
                session="boot-1/run-2",
            ),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=100),
                rx=2_000,
                tx=900,
                sequence="2",
                session="boot-1/run-2",
            ),
            max_gap=timedelta(seconds=30),
        )

        assert intervals(service) == []
        assert [item.reason for item in discontinuities(service)] == [
            "collector_session_changed",
            "measurement_gap",
        ]


def test_interface_switch_creates_new_baseline(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, en0_download, en0_upload = setup_tracking(service)
        service.record_interface_observation(
            pair(en0_download, en0_upload, at=BASE, rx=5_000, tx=1_000, sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        _, en1_download, en1_upload = service.ensure_interface_setup(
            "en1", "test-provider", "audited-connection"
        )
        service.record_interface_observation(
            pair(
                en1_download,
                en1_upload,
                at=BASE + timedelta(seconds=10),
                rx=100,
                tx=50,
                sequence="2",
            ),
            max_gap=timedelta(seconds=30),
        )

        assert intervals(service) == []
        assert [item.reason for item in discontinuities(service)] == ["interface_changed"]


def test_pair_idempotency_conflict_and_large_exact_counters(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        first = pair(
            download,
            upload,
            at=BASE,
            rx=9_000_000_000_000,
            tx=8_000_000_000_000,
            sequence="same",
        )
        service.record_interface_observation(first, max_gap=timedelta(seconds=30))
        _, _, created = service.record_interface_observation(
            first, max_gap=timedelta(seconds=30)
        )
        assert created is False
        assert intervals(service) == []
        with pytest.raises(ConflictError):
            service.record_interface_observation(
                first.model_copy(
                    update={
                        "download": first.download.model_copy(
                            update={"raw_counter_bytes": 9_000_000_000_001}
                        )
                    }
                ),
                max_gap=timedelta(seconds=30),
            )


@pytest.mark.parametrize("rx_delta,tx_delta", [(0, 0), (1, 2), (999_999, 4_294_967_296)])
def test_monotonic_deltas_are_nonnegative_and_exact(
    database: Database, rx_delta: int, tx_delta: int
) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=10_000, tx=20_000, sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=1),
                rx=10_000 + rx_delta,
                tx=20_000 + tx_delta,
                sequence="2",
            ),
            max_gap=timedelta(seconds=30),
        )
        assert sorted(item.delta_bytes for item in intervals(service)) == sorted(
            [rx_delta, tx_delta]
        )


def test_active_window_aggregation_excludes_partial_interval(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(service)
        experiment.started_at = BASE + timedelta(seconds=5)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(download, upload, at=BASE + timedelta(seconds=10), rx=1_600, tx=800, sequence="2"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(download, upload, at=BASE + timedelta(seconds=20), rx=2_000, tx=900, sequence="3"),
            max_gap=timedelta(seconds=30),
        )
        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=25))

        assert usage.observed_rx_bytes == 400
        assert usage.observed_tx_bytes == 100
        assert usage.total_observed_bytes == 500
        assert usage.covered_duration_seconds == 10
        assert usage.eligible_duration_seconds == 20
        assert usage.coverage_percent == 50.0
        assert usage.has_coverage_gaps is True


def test_no_observations_returns_waiting_unknown_not_zero(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        setup_tracking(service)
        usage = service.current_experiment_usage(now=BASE)

        assert usage.status == "waiting"
        assert usage.total_observed_bytes is None
        assert usage.tracking_baseline_bytes is None
        assert usage.accounted_remainder_bytes is None
        assert usage.coverage_percent == 0.0


@pytest.mark.parametrize(
    ("starting_balance", "expected_baseline", "expected_remainder"),
    [
        ("30", 30_000_000_000, 29_000_000_000),
        ("23.91", 23_910_000_000, 22_910_000_000),
    ],
)
def test_accounted_remainder_uses_tracking_start_balance(
    database: Database,
    starting_balance: str,
    expected_baseline: int,
    expected_remainder: int,
) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(service)
        record_remaining_balance(service, experiment.id, starting_balance)
        record_usage(service, download, upload, rx_delta=800_000_000, tx_delta=200_000_000)

        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=10))
        bundle = service.repository.get_bundle(experiment.data_bundle_id)

        assert usage.tracking_baseline_bytes == expected_baseline
        assert usage.total_observed_bytes == 1_000_000_000
        assert usage.accounted_remainder_bytes == expected_remainder
        assert bundle is not None
        assert bundle.allowance_bytes == 30_000_000_000


def test_tiny_usage_preserves_partial_bundle_baseline(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(service)
        record_remaining_balance(service, experiment.id, "23.91")
        record_usage(service, download, upload, rx_delta=200_000, tx_delta=15_200)

        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=10))

        assert usage.tracking_baseline_bytes == 23_910_000_000
        assert usage.total_observed_bytes == 215_200
        assert usage.accounted_remainder_bytes == 23_909_784_800


def test_later_provider_update_does_not_reset_tracking_baseline(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(service)
        initial = record_remaining_balance(service, experiment.id, "23.91")
        later = record_remaining_balance(
            service,
            experiment.id,
            "20",
            timestamp=BASE - timedelta(days=1),
        )
        record_usage(service, download, upload, rx_delta=800_000_000, tx_delta=200_000_000)

        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=10))

        assert initial.created_at < later.created_at
        assert usage.tracking_baseline_bytes == 23_910_000_000
        assert usage.accounted_remainder_bytes == 22_910_000_000


def test_stopped_collector_reports_tracking_paused(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="1"),
            max_gap=timedelta(seconds=30),
        )
        run = service.start_collector_run(None)
        run.started_at = BASE - timedelta(seconds=1)
        service.finish_collector_run(run.id, "stopped")
        run.ended_at = BASE + timedelta(seconds=1)

        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=2))

        assert usage.status == "interrupted"
        assert usage.message == "Tracking is currently paused."


def test_delayed_first_observation_records_real_historical_gap(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(service)
        experiment.started_at = BASE
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=40),
                rx=1_000,
                tx=500,
                sequence="1",
            ),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=50),
                rx=1_600,
                tx=800,
                sequence="2",
            ),
            max_gap=timedelta(seconds=30),
        )

        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=50))

        assert usage.status == "active"
        assert usage.has_coverage_gaps is True
        assert [item.reason for item in discontinuities(service)] == ["measurement_gap"]


def test_installed_but_stopped_service_overrides_recent_observation(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="1"),
            max_gap=timedelta(seconds=30),
        )

        usage = service.current_experiment_usage(
            now=BASE + timedelta(seconds=1),
            lifecycle=SensorLifecycleState(True, False, False),
        )

        assert usage.status == "paused"
        assert usage.service_installed is True
        assert usage.service_expected_to_run is False


def test_loaded_service_without_recent_measurement_is_not_healthy(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        setup_tracking(service)

        usage = service.current_experiment_usage(
            now=BASE,
            lifecycle=SensorLifecycleState(True, True, False),
        )

        assert usage.status == "waiting"
        assert usage.message == "The measurement sensor is starting."


def test_audit_accumulates_trusted_periods_across_restart(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(service)
        record_remaining_balance(service, experiment.id, "23.91")
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="a0"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=10),
                rx=4_000_001_000,
                tx=1_000_000_500,
                sequence="a1",
            ),
            max_gap=timedelta(seconds=30),
        )
        at_break = service.current_experiment_usage(now=BASE + timedelta(seconds=10))
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=20),
                rx=4_100_001_000,
                tx=1_100_000_500,
                sequence="b0",
                session="boot-1/run-2",
            ),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=30),
                rx=6_000_001_000,
                tx=1_500_000_500,
                sequence="b1",
                session="boot-1/run-2",
            ),
            max_gap=timedelta(seconds=30),
        )

        current = service.current_experiment_usage(now=BASE + timedelta(seconds=30))
        historical = service.current_experiment_usage(now=BASE + timedelta(seconds=10))

        assert experiment.status == "active"
        assert at_break.total_observed_bytes == 5_000_000_000
        assert at_break.accounted_remainder_bytes == 18_910_000_000
        assert current.total_observed_bytes == 7_300_000_000
        assert current.accounted_remainder_bytes == 16_610_000_000
        assert historical.total_observed_bytes == 5_000_000_000
        assert historical.accounted_remainder_bytes == 18_910_000_000
        assert current.has_unknown_gaps is True
        assert [item.reason for item in discontinuities(service)] == [
            "collector_session_changed"
        ]


def test_connection_change_on_same_interface_is_not_silently_rebound(
    database: Database,
) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, _, _ = setup_tracking(service)
        original_source = experiment.measurement_source_id

        with pytest.raises(ConnectionAttributionError):
            service.ensure_interface_setup("en0", "test-provider", "different-connection")

        assert experiment.status == "active"
        assert experiment.measurement_source_id == original_source


def test_explicit_legacy_connection_confirmation_preserves_history_and_baseline(
    database: Database,
) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, download, upload = setup_tracking(
            service, connection_fingerprint=None
        )
        source_id = experiment.measurement_source_id
        record_remaining_balance(service, experiment.id, "23.91")
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="a0"),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=10),
                rx=4_000_001_000,
                tx=1_000_000_500,
                sequence="a1",
            ),
            max_gap=timedelta(seconds=30),
        )
        before = service.current_experiment_usage(now=BASE + timedelta(seconds=10))
        experiment.measurement_source_id = None

        with pytest.raises(ConnectionAttributionError):
            # A new identity cannot be inferred into a legacy source automatically.
            experiment.measurement_source_id = source_id
            service.ensure_interface_setup("en0", "test-provider", "confirmed-connection")
        experiment.measurement_source_id = None
        service.confirm_active_audit_connection(
            "en0", "confirmed-connection", experiment_id=experiment.id
        )
        source, confirmed_download, confirmed_upload = service.ensure_interface_setup(
            "en0", "test-provider", "confirmed-connection"
        )

        assert source.id == source_id
        assert confirmed_download.id == download.id
        assert confirmed_upload.id == upload.id
        after_confirmation = service.current_experiment_usage(
            now=BASE + timedelta(seconds=10)
        )
        assert after_confirmation.total_observed_bytes == 5_000_000_000
        assert after_confirmation.tracking_baseline_bytes == 23_910_000_000

        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=20),
                rx=4_100_001_000,
                tx=1_100_000_500,
                sequence="b0",
                session="boot-1/run-2",
            ),
            max_gap=timedelta(seconds=30),
        )
        service.record_interface_observation(
            pair(
                download,
                upload,
                at=BASE + timedelta(seconds=30),
                rx=6_000_001_000,
                tx=1_500_000_500,
                sequence="b1",
                session="boot-1/run-2",
            ),
            max_gap=timedelta(seconds=30),
        )
        current = service.current_experiment_usage(now=BASE + timedelta(seconds=30))

        assert before.total_observed_bytes == 5_000_000_000
        assert experiment.id == after_confirmation.experiment_id == current.experiment_id
        assert current.total_observed_bytes == 7_300_000_000
        assert current.accounted_remainder_bytes == 16_610_000_000
        assert service.repository.initial_remaining_balance(experiment.id) is not None


def test_connection_confirmation_refuses_ambiguous_active_audits(
    database: Database,
) -> None:
    with database.session() as session:
        service = DachikService(session)
        experiment, _, _ = setup_tracking(service, connection_fingerprint=None)
        second = service.create_experiment(
            schemas.ExperimentCreate(
                data_bundle_id=experiment.data_bundle_id,
                device_id=experiment.device_id,
                methodology_version="test-v1",
            )
        )
        second.status = "active"
        second.started_at = BASE
        service.repository.clear_tracking_target(experiment.id)

        with pytest.raises(ConflictError, match="exactly one active audit"):
            service.confirm_active_audit_connection("en0", "confirmed-connection")


def test_v1_current_plan_selection_never_uses_newest_active_row(
    database: Database,
) -> None:
    with database.session() as session:
        service = DachikService(session)
        assert service.current_experiment() is None
        first, _, _ = setup_tracking(service)
        assert service.current_experiment() is first

        second = service.create_experiment(
            schemas.ExperimentCreate(
                data_bundle_id=first.data_bundle_id,
                device_id=first.device_id,
                methodology_version="test-v1",
            )
        )
        with pytest.raises(ConflictError, match="already being tracked"):
            service.start_experiment(second.id)

        switched = service.start_experiment(second.id, switch_current=True)
        assert service.current_experiment() is switched
        assert first.status == "active"
        assert switched.status == "active"

        service.repository.session.delete(service.repository.get_current_tracking_target())
        service.repository.session.flush()
        with pytest.raises(MultipleActivePlansError):
            service.current_experiment()
        usage = service.current_experiment_usage(now=BASE)
        assert usage.status == "multiple_active_plans"
        assert usage.experiment_id is None
        assert first.status == switched.status == "active"


def test_known_non_attributable_period_is_separate_from_unknown_gap(
    database: Database,
) -> None:
    with database.session() as session:
        service = DachikService(session)
        _, download, upload = setup_tracking(service)
        service.record_interface_observation(
            pair(download, upload, at=BASE, rx=1_000, tx=500, sequence="baseline"),
            max_gap=timedelta(seconds=30),
        )
        service.record_connection_unavailable(
            "connection_changed", at=BASE + timedelta(seconds=20)
        )

        usage = service.current_experiment_usage(now=BASE + timedelta(seconds=20))

        assert usage.known_inactive_duration_seconds == 20
        assert usage.unknown_duration_seconds == 1
        assert usage.has_unknown_gaps is True
        assert usage.total_observed_bytes is None
