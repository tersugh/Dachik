"""Normalized SQLite domain model for Dachik V1."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime, TypeDecorator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Persist aware datetimes as normalized naive UTC and restore UTC awareness."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Direction(StrEnum):
    DOWNLOAD = "download"
    UPLOAD = "upload"


class SnapshotType(StrEnum):
    REMAINING_BALANCE = "remaining_balance"
    CUMULATIVE_CONSUMPTION = "cumulative_consumption"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    hostname: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    operating_system: Mapped[str] = mapped_column(String(100))
    operating_system_version: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class TrafficSource(Base):
    __tablename__ = "traffic_sources"
    __table_args__ = (
        CheckConstraint(
            "domain IN ('measured.interface', 'attributed.process', "
            "'measured.gateway_wan', 'attributed.device')",
            name="ck_traffic_source_domain",
        ),
        CheckConstraint("unit = 'bytes'", name="ck_traffic_source_unit"),
        UniqueConstraint("provider_type", "name", "scope", name="uq_traffic_source_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_type: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(20), default="bytes")
    monotonic: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_version: Mapped[str | None] = mapped_column(String(100))
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    stable_identifier: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CounterSeries(Base):
    __tablename__ = "counter_series"
    __table_args__ = (
        CheckConstraint("direction IN ('download', 'upload')", name="ck_counter_series_direction"),
        CheckConstraint(
            "accounting_domain IN ('measured.interface', 'attributed.process', "
            "'measured.gateway_wan', 'attributed.device')",
            name="ck_counter_series_domain",
        ),
        UniqueConstraint(
            "source_id",
            "device_id",
            "direction",
            "identity",
            "accounting_domain",
            "scope",
            name="uq_counter_series_identity",
        ),
        Index("ix_counter_series_source_device", "source_id", "device_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("traffic_sources.id", ondelete="RESTRICT"))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="RESTRICT"))
    direction: Mapped[str] = mapped_column(String(20))
    identity: Mapped[str] = mapped_column(String(255))
    accounting_domain: Mapped[str] = mapped_column(String(50))
    scope: Mapped[str] = mapped_column(String(255))
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CounterObservation(Base):
    __tablename__ = "counter_observations"
    __table_args__ = (
        CheckConstraint("raw_counter_bytes >= 0", name="ck_observation_bytes_nonnegative"),
        UniqueConstraint(
            "counter_series_id", "session_id", "sequence_key", name="uq_observation_idempotency"
        ),
        Index("ix_observation_series_timestamp", "counter_series_id", "timestamp_utc"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    counter_series_id: Mapped[str] = mapped_column(
        ForeignKey("counter_series.id", ondelete="RESTRICT")
    )
    timestamp_utc: Mapped[datetime] = mapped_column(UTCDateTime())
    monotonic_timestamp_ns: Mapped[int] = mapped_column(BigInteger)
    raw_counter_bytes: Mapped[int] = mapped_column(BigInteger)
    session_id: Mapped[str] = mapped_column(String(255))
    sequence_key: Mapped[str] = mapped_column(String(255))
    collector_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class UsageInterval(Base):
    __tablename__ = "usage_intervals"
    __table_args__ = (
        CheckConstraint("delta_bytes >= 0", name="ck_usage_delta_nonnegative"),
        CheckConstraint("end_timestamp > start_timestamp", name="ck_usage_time_order"),
        UniqueConstraint(
            "counter_series_id",
            "start_timestamp",
            "end_timestamp",
            "methodology_version",
            name="uq_usage_interval_derivation",
        ),
        Index("ix_usage_interval_series_time", "counter_series_id", "start_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    counter_series_id: Mapped[str] = mapped_column(
        ForeignKey("counter_series.id", ondelete="CASCADE")
    )
    start_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    end_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    delta_bytes: Mapped[int] = mapped_column(BigInteger)
    quality: Mapped[str] = mapped_column(String(50))
    discontinuity_reason: Mapped[str | None] = mapped_column(String(100))
    methodology_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ApplicationUsage(Base):
    __tablename__ = "application_usage"
    __table_args__ = (
        CheckConstraint("received_bytes >= 0", name="ck_application_rx_nonnegative"),
        CheckConstraint("transmitted_bytes >= 0", name="ck_application_tx_nonnegative"),
        CheckConstraint("bucket_end > bucket_start", name="ck_application_usage_time_order"),
        Index("ix_application_usage_time", "application_id", "bucket_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="RESTRICT"))
    source_id: Mapped[str] = mapped_column(ForeignKey("traffic_sources.id", ondelete="RESTRICT"))
    bucket_start: Mapped[datetime] = mapped_column(UTCDateTime())
    bucket_end: Mapped[datetime] = mapped_column(UTCDateTime())
    received_bytes: Mapped[int] = mapped_column(BigInteger)
    transmitted_bytes: Mapped[int] = mapped_column(BigInteger)
    quality: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class DataBundle(Base):
    __tablename__ = "data_bundles"
    __table_args__ = (
        CheckConstraint("allowance_bytes > 0", name="ck_bundle_allowance_positive"),
        CheckConstraint("billing_cycle_end > billing_cycle_start", name="ck_bundle_time_order"),
        Index("ix_bundle_provider_created", "provider_name", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_name: Mapped[str] = mapped_column(String(255))
    plan_name: Mapped[str] = mapped_column(String(255))
    allowance_bytes: Mapped[int] = mapped_column(BigInteger)
    billing_cycle_start: Mapped[datetime] = mapped_column(UTCDateTime())
    billing_cycle_end: Mapped[datetime] = mapped_column(UTCDateTime())
    timezone: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class DataAuditExperiment(Base):
    __tablename__ = "data_audit_experiments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'cancelled')",
            name="ck_experiment_status",
        ),
        CheckConstraint(
            "ended_at IS NULL OR started_at IS NOT NULL AND ended_at >= started_at",
            name="ck_experiment_time_order",
        ),
        Index("ix_experiment_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    data_bundle_id: Mapped[str] = mapped_column(ForeignKey("data_bundles.id", ondelete="RESTRICT"))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="RESTRICT"))
    measurement_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("traffic_sources.id", ondelete="RESTRICT")
    )
    measurement_boundary: Mapped[str] = mapped_column(String(100), default="measured.interface")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default=ExperimentStatus.DRAFT.value)
    methodology_version: Mapped[str] = mapped_column(String(100))
    user_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ISPBalanceSnapshot(Base):
    __tablename__ = "isp_balance_snapshots"
    __table_args__ = (
        CheckConstraint(
            "normalized_bytes IS NULL OR normalized_bytes >= 0", name="ck_snapshot_bytes"
        ),
        CheckConstraint(
            "snapshot_type IN ('remaining_balance', 'cumulative_consumption')",
            name="ck_snapshot_type",
        ),
        CheckConstraint("provenance = 'manual'", name="ck_snapshot_provenance"),
        Index("ix_snapshot_experiment_timestamp", "experiment_id", "timestamp_utc"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("data_audit_experiments.id", ondelete="RESTRICT")
    )
    timestamp_utc: Mapped[datetime] = mapped_column(UTCDateTime())
    reported_value: Mapped[str] = mapped_column(String(100))
    reported_unit: Mapped[str] = mapped_column(String(30))
    snapshot_type: Mapped[str] = mapped_column(String(50))
    normalized_bytes: Mapped[int | None] = mapped_column(BigInteger)
    provenance: Mapped[str] = mapped_column(String(50), default="manual")
    note: Mapped[str | None] = mapped_column(Text)
    correction_of_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("isp_balance_snapshots.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CollectorRun(Base):
    __tablename__ = "collector_runs"
    __table_args__ = (Index("ix_collector_run_source_started", "source_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("traffic_sources.id", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    collector_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50))
    health_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class MeasurementDiscontinuity(Base):
    __tablename__ = "measurement_discontinuities"
    __table_args__ = (
        CheckConstraint("end_timestamp > start_timestamp", name="ck_discontinuity_time_order"),
        Index("ix_discontinuity_experiment_time", "experiment_id", "start_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_audit_experiments.id", ondelete="CASCADE")
    )
    counter_series_id: Mapped[str | None] = mapped_column(
        ForeignKey("counter_series.id", ondelete="CASCADE")
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("traffic_sources.id", ondelete="RESTRICT")
    )
    start_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    end_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    reason: Mapped[str] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
