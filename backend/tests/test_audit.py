import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.app import schemas
from backend.app.audit import AuditEngine
from backend.app.database import Database
from backend.app.reports import (
    audit_csv,
    audit_json,
    audit_pdf,
    format_bytes,
    format_local_timestamp,
)
from backend.app.services import DachikService

BASE = datetime(2026, 8, 17, 7, tzinfo=UTC)


def test_local_timestamp_formatter_preserves_utc_evidence() -> None:
    raw = datetime(2026, 8, 18, 19, 54, 41, 725503, tzinfo=UTC)

    assert format_local_timestamp(
        raw, "Africa/Lagos", include_seconds=True
    ) == "18 Aug 2026 · 20:54:41"
    assert format_local_timestamp(
        raw, "America/New_York", include_seconds=True
    ) == "18 Aug 2026 · 15:54:41"
    assert raw == datetime(2026, 8, 18, 19, 54, 41, 725503, tzinfo=UTC)


@pytest.mark.parametrize(
    ("measured_hours", "known_hours", "unknown_hours", "coverage", "quality"),
    [
        (10, 0, 0, 100.0, "excellent"),
        (9.5, 0, 0.5, 95.0, "excellent"),
        (8, 0, 2, 80.0, "limited"),
        (1, 0, 9, 10.0, "insufficient"),
        (8, 8, 0, 100.0, "excellent"),
        (8, 8, 8, 50.0, "insufficient"),
    ],
)
def test_audit_evidence_quality_excludes_known_non_attributable_time(
    measured_hours: float,
    known_hours: float,
    unknown_hours: float,
    coverage: float,
    quality: str,
) -> None:
    measured_seconds = int(measured_hours * 3600)
    known_seconds = int(known_hours * 3600)
    unknown_seconds = int(unknown_hours * 3600)

    actual = AuditEngine._coverage(measured_seconds, unknown_seconds)

    assert actual == coverage
    assert AuditEngine._quality(actual) == quality
    quality_relevant_seconds = measured_seconds + unknown_seconds
    if known_seconds:
        assert quality_relevant_seconds != (
            measured_seconds + known_seconds + unknown_seconds
        )


def setup_audit(service: DachikService) -> tuple[str, str, str]:
    device = service.create_device(
        schemas.DeviceCreate(
            hostname="audit-test-mac",
            display_name="Audit test Mac",
            operating_system="macOS",
        )
    )
    bundle = service.create_bundle(
        schemas.DataBundleCreate(
            provider_name="Synthetic Network",
            plan_name="30 GB audit plan",
            allowance_bytes=30_000_000_000,
            billing_cycle_start=BASE,
            billing_cycle_end=BASE + timedelta(days=30),
            timezone="Africa/Lagos",
        )
    )
    experiment = service.create_experiment(
        schemas.ExperimentCreate(
            data_bundle_id=bundle.id,
            device_id=device.id,
            methodology_version="audit-v1",
        )
    )
    service.start_experiment(experiment.id)
    experiment.started_at = BASE
    _, download, upload = service.ensure_interface_setup(
        "en0", "test", "audit-connection"
    )
    service.create_snapshot(
        experiment.id,
        schemas.ISPBalanceSnapshotCreate(
            timestamp_utc=BASE,
            reported_value="23.91",
            reported_unit="GB",
            snapshot_type="remaining_balance",
        ),
    )
    return experiment.id, download.id, upload.id


def observation(
    download_id: str,
    upload_id: str,
    timestamp: datetime,
    rx: int,
    tx: int,
    sequence: str,
    session: str = "boot/run-1",
) -> schemas.InterfaceObservationCreate:
    monotonic = 10_000_000_000 + int((timestamp - BASE).total_seconds() * 1_000_000_000)
    return schemas.InterfaceObservationCreate(
        download=schemas.CounterObservationCreate(
            counter_series_id=download_id,
            timestamp_utc=timestamp,
            monotonic_timestamp_ns=monotonic,
            raw_counter_bytes=rx,
            session_id=session,
            sequence_key=sequence,
            collector_version="test",
        ),
        upload=schemas.CounterObservationCreate(
            counter_series_id=upload_id,
            timestamp_utc=timestamp,
            monotonic_timestamp_ns=monotonic,
            raw_counter_bytes=tx,
            session_id=session,
            sequence_key=sequence,
            collector_version="test",
        ),
    )


def record_pair(
    service: DachikService,
    download_id: str,
    upload_id: str,
    first: datetime,
    second: datetime,
    rx_delta: int,
    tx_delta: int,
    *,
    session: str = "boot/run-1",
    prefix: str = "a",
) -> None:
    service.record_interface_observation(
        observation(download_id, upload_id, first, 1_000, 500, f"{prefix}0", session),
        max_gap=timedelta(hours=2),
    )
    service.record_interface_observation(
        observation(
            download_id,
            upload_id,
            second,
            1_000 + rx_delta,
            500 + tx_delta,
            f"{prefix}1",
            session,
        ),
        max_gap=timedelta(hours=2),
    )


def test_point_in_time_breaks_and_original_baseline(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        audit_id, download, upload = setup_audit(service)
        record_pair(
            service, download, upload, BASE, BASE + timedelta(minutes=10),
            4_000_000_000, 1_000_000_000,
        )
        record_pair(
            service,
            download,
            upload,
            BASE + timedelta(minutes=20),
            BASE + timedelta(minutes=30),
            1_900_000_000,
            400_000_000,
            session="boot/run-2",
            prefix="b",
        )
        engine = AuditEngine(service.repository)

        early = engine.build(audit_id, as_of=BASE + timedelta(minutes=10))
        current = engine.build(audit_id, as_of=BASE + timedelta(minutes=30))

        assert early.total_observed_bytes == 5_000_000_000
        assert early.accounted_remainder_bytes == 18_910_000_000
        assert current.total_observed_bytes == 7_300_000_000
        assert current.accounted_remainder_bytes == 16_610_000_000
        assert current.initial_tracking_balance_bytes == 23_910_000_000
        assert current.unknown_duration_seconds > 0


def test_aligned_isp_comparison_and_neutral_insufficient_language(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        audit_id, download, upload = setup_audit(service)
        record_pair(
            service, download, upload, BASE, BASE + timedelta(minutes=30),
            3_000_000_000, 400_000_000,
        )
        service.create_snapshot(
            audit_id,
            schemas.ISPBalanceSnapshotCreate(
                timestamp_utc=BASE + timedelta(hours=1),
                reported_value="20",
                reported_unit="GB",
                snapshot_type="remaining_balance",
            ),
        )
        state = AuditEngine(service.repository).build(
            audit_id, as_of=BASE + timedelta(hours=1)
        )

        comparison = state.comparisons[0]
        assert comparison.provider_deduction_bytes == 3_910_000_000
        assert comparison.dachik_usage_bytes == 3_400_000_000
        assert comparison.observed_difference_bytes == 510_000_000
        assert comparison.evidence_quality == "insufficient"
        assert "enough evidence" in comparison.conclusion


def test_timezone_buckets_unknown_hours_and_export_consistency(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        audit_id, download, upload = setup_audit(service)
        record_pair(
            service,
            download,
            upload,
            BASE + timedelta(minutes=55),
            BASE + timedelta(hours=1, minutes=5),
            800_000_000,
            200_000_000,
        )
        state = AuditEngine(service.repository).build(
            audit_id, as_of=BASE + timedelta(hours=3)
        )
        payload = json.loads(audit_json(state))
        csv_text = audit_csv(state).decode("utf-8")
        pdf = audit_pdf(state)

        assert any(item.boundary_spanning_bytes == 1_000_000_000 for item in state.hourly)
        assert any(item.state == "unknown" for item in state.hourly)
        assert payload["total_observed_bytes"] == state.total_observed_bytes
        assert payload["as_of_timestamp"] == state.as_of_timestamp.isoformat().replace(
            "+00:00", "Z"
        )
        assert f"total_trusted_bytes,{state.total_observed_bytes}" in csv_text
        assert pdf.startswith(b"%PDF")
        assert b"Times shown in Africa/Lagos" in pdf
        assert b"Generated through 17 Aug 2026" in pdf
        assert b"08:00:00" in pdf
        assert state.as_of_timestamp.isoformat().encode() not in pdf
        assert b"audit-connection" not in pdf
        assert b"connection_fingerprint" not in pdf


def test_provider_exhaustion_language_depends_on_evidence(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        audit_id, download, upload = setup_audit(service)
        record_pair(
            service,
            download,
            upload,
            BASE,
            BASE + timedelta(hours=1),
            18_000_000_000,
            200_000_000,
        )
        service.create_snapshot(
            audit_id,
            schemas.ISPBalanceSnapshotCreate(
                timestamp_utc=BASE + timedelta(hours=1),
                reported_value="0",
                reported_unit="GB",
                snapshot_type="remaining_balance",
            ),
        )

        strong = AuditEngine(service.repository).build(
            audit_id, as_of=BASE + timedelta(hours=1)
        )
        assert strong.comparisons[0].evidence_quality == "excellent"
        assert strong.comparisons[0].conclusion == (
            "Possible accounting discrepancy worth reviewing."
        )

def test_provider_exhaustion_with_gap_stays_neutral(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        audit_id_2, download_2, upload_2 = setup_audit(service)
        record_pair(
            service,
            download_2,
            upload_2,
            BASE,
            BASE + timedelta(minutes=10),
            2_000_000_000,
            100_000_000,
            prefix="gap",
        )
        service.create_snapshot(
            audit_id_2,
            schemas.ISPBalanceSnapshotCreate(
                timestamp_utc=BASE + timedelta(hours=1),
                reported_value="0",
                reported_unit="GB",
                snapshot_type="remaining_balance",
            ),
        )
        insufficient = AuditEngine(service.repository).build(
            audit_id_2, as_of=BASE + timedelta(hours=1)
        )
        assert insufficient.comparisons[0].evidence_quality == "insufficient"
        assert "enough evidence" in insufficient.comparisons[0].conclusion


def test_final_report_and_integer_safe_display(database: Database) -> None:
    with database.session() as session:
        service = DachikService(session)
        audit_id, _, _ = setup_audit(service)
        experiment = service.repository.get_experiment(audit_id)
        assert experiment is not None
        experiment.status = "completed"
        experiment.ended_at = BASE + timedelta(hours=1)
        state = AuditEngine(service.repository).build(
            audit_id, as_of=BASE + timedelta(hours=2)
        )
        assert state.audit_status == "final"
        assert b"Final" in audit_pdf(state)
        assert format_bytes(30_000_000_000) == "30 GB"
