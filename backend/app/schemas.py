"""Typed request and response schemas for the local API."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveBytes = Annotated[int, Field(gt=0)]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(APIModel):
    status: Literal["ok"] = "ok"
    service: Literal["dachik"] = "dachik"
    version: str


class ErrorResponse(APIModel):
    error: str
    detail: str


class DeviceCreate(APIModel):
    hostname: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    operating_system: str = Field(min_length=1, max_length=100)
    operating_system_version: str | None = Field(default=None, max_length=100)


class DeviceResponse(DeviceCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class DataBundleCreate(APIModel):
    provider_name: str = Field(min_length=1, max_length=255)
    plan_name: str = Field(min_length=1, max_length=255)
    allowance_bytes: PositiveBytes
    billing_cycle_start: datetime
    billing_cycle_end: datetime
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("billing_cycle_start", "billing_cycle_end")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset")
        return value

    @field_validator("timezone")
    @classmethod
    def require_valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def require_ordered_cycle(self) -> "DataBundleCreate":
        if self.billing_cycle_end <= self.billing_cycle_start:
            raise ValueError("billing_cycle_end must be after billing_cycle_start")
        return self


class DataBundleResponse(DataBundleCreate):
    id: str
    created_at: datetime


class ExperimentCreate(APIModel):
    data_bundle_id: str
    device_id: str
    measurement_source_id: str | None = None
    measurement_boundary: str = Field(default="measured.interface", min_length=1, max_length=100)
    methodology_version: str = Field(min_length=1, max_length=100)
    user_notes: str | None = Field(default=None, max_length=4000)


class ExperimentResponse(ExperimentCreate):
    id: str
    started_at: datetime | None
    ended_at: datetime | None
    status: Literal["draft", "active", "completed", "cancelled"]
    created_at: datetime


class CurrentTrackingSelection(APIModel):
    experiment_id: str


class ISPBalanceSnapshotCreate(APIModel):
    timestamp_utc: datetime
    reported_value: str = Field(min_length=1, max_length=100)
    reported_unit: str = Field(min_length=1, max_length=30)
    snapshot_type: Literal["remaining_balance", "cumulative_consumption"]
    provenance: Literal["manual"] = "manual"
    note: str | None = Field(default=None, max_length=2000)
    correction_of_snapshot_id: str | None = None

    @field_validator("timestamp_utc")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset")
        return value


class ISPBalanceSnapshotResponse(ISPBalanceSnapshotCreate):
    id: str
    experiment_id: str
    normalized_bytes: int | None
    created_at: datetime


class TrafficSourceCreate(APIModel):
    provider_type: str
    domain: Literal[
        "measured.interface", "attributed.process", "measured.gateway_wan", "attributed.device"
    ]
    name: str
    scope: str
    unit: Literal["bytes"] = "bytes"
    monotonic: bool = True
    active: bool = True
    provider_version: str | None = None


class CounterSeriesCreate(APIModel):
    source_id: str
    device_id: str
    direction: Literal["download", "upload"]
    identity: str
    accounting_domain: Literal[
        "measured.interface", "attributed.process", "measured.gateway_wan", "attributed.device"
    ]
    scope: str
    application_id: str | None = None


class CounterObservationCreate(APIModel):
    counter_series_id: str
    timestamp_utc: datetime
    monotonic_timestamp_ns: Annotated[int, Field(ge=0)]
    raw_counter_bytes: Annotated[int, Field(ge=0)]
    session_id: str
    sequence_key: str
    collector_version: str

    @field_validator("timestamp_utc")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset")
        return value


class InterfaceObservationCreate(APIModel):
    download: CounterObservationCreate
    upload: CounterObservationCreate

    @model_validator(mode="after")
    def require_paired_observation(self) -> "InterfaceObservationCreate":
        if self.download.timestamp_utc != self.upload.timestamp_utc:
            raise ValueError("paired observations must have the same timestamp")
        if self.download.session_id != self.upload.session_id:
            raise ValueError("paired observations must have the same session")
        if self.download.sequence_key != self.upload.sequence_key:
            raise ValueError("paired observations must have the same sequence key")
        return self


class MeasurementStatusResponse(APIModel):
    status: Literal[
        "no_active_plan",
        "multiple_active_plans",
        "waiting",
        "active",
        "paused",
        "interrupted",
        "unavailable",
        "ambiguous",
    ]
    latest_observation_at: datetime | None
    interface_name: str | None
    service_installed: bool
    service_expected_to_run: bool
    collector_run_status: str | None
    message: str


class CurrentExperimentUsageResponse(APIModel):
    experiment_id: str | None
    status: Literal[
        "no_active_plan",
        "multiple_active_plans",
        "waiting",
        "active",
        "paused",
        "interrupted",
        "unavailable",
        "ambiguous",
    ]
    tracking_started_at: datetime | None
    as_of_timestamp: datetime
    latest_observation_at: datetime | None
    observed_rx_bytes: int | None
    observed_tx_bytes: int | None
    total_observed_bytes: int | None
    tracking_baseline_bytes: int | None
    latest_provider_balance_bytes: int | None
    accounted_remainder_bytes: int | None
    covered_duration_seconds: int
    eligible_duration_seconds: int
    coverage_percent: float | None
    known_inactive_duration_seconds: int
    unknown_duration_seconds: int
    has_coverage_gaps: bool
    has_unknown_gaps: bool
    interface_name: str | None
    service_installed: bool
    service_expected_to_run: bool
    collector_run_status: str | None
    message: str


EvidenceQuality = Literal["excellent", "good", "limited", "insufficient"]
AuditStatus = Literal["in_progress", "final"]


class AuditBucket(APIModel):
    start: datetime
    end: datetime
    observed_rx_bytes: int
    observed_tx_bytes: int
    total_observed_bytes: int
    starting_accounted_remainder_bytes: int | None
    ending_accounted_remainder_bytes: int | None
    measured_duration_seconds: int
    known_inactive_duration_seconds: int
    unknown_duration_seconds: int
    boundary_spanning_bytes: int
    state: Literal["measured", "known_inactive", "unknown", "mixed"]


class AuditEvent(APIModel):
    timestamp: datetime
    event_type: Literal[
        "connection_changed",
        "measurement_interrupted",
        "measurement_resumed",
        "network_balance_updated",
    ]
    description: str
    reported_balance_bytes: int | None = None
    accounted_remainder_bytes: int | None = None


class ISPComparisonWindow(APIModel):
    start_timestamp: datetime
    end_timestamp: datetime
    start_balance_bytes: int
    end_balance_bytes: int
    provider_deduction_bytes: int
    dachik_usage_bytes: int
    observed_difference_bytes: int
    measured_duration_seconds: int
    known_inactive_duration_seconds: int
    unknown_duration_seconds: int
    evidence_coverage_percent: float
    evidence_quality: EvidenceQuality
    conclusion: str


class AuditSnapshotCheckpoint(APIModel):
    timestamp: datetime
    reported_value: str
    reported_unit: str
    normalized_bytes: int | None
    accounted_remainder_bytes: int | None
    note: str | None


class AuditState(APIModel):
    audit_id: str
    provider_name: str
    plan_name: str
    original_allowance_bytes: int
    bundle_start: datetime
    bundle_expiry: datetime
    timezone: str
    audit_status: AuditStatus
    audit_start: datetime
    as_of_timestamp: datetime
    initial_tracking_balance_bytes: int | None
    latest_provider_balance_bytes: int | None
    observed_rx_bytes: int
    observed_tx_bytes: int
    total_observed_bytes: int
    accounted_remainder_bytes: int | None
    usage_exceeds_starting_balance: bool
    latest_trusted_observation: datetime | None
    sensor_status: str
    measured_duration_seconds: int
    known_inactive_duration_seconds: int
    unknown_duration_seconds: int
    evidence_coverage_percent: float
    evidence_quality: EvidenceQuality
    has_unknown_gaps: bool
    daily: list[AuditBucket]
    hourly: list[AuditBucket]
    events: list[AuditEvent]
    isp_checkpoints: list[AuditSnapshotCheckpoint]
    comparisons: list[ISPComparisonWindow]
    methodology_version: str
    measurement_boundary: str
    limitations: list[str]


class AuditListItem(APIModel):
    audit_id: str
    provider_name: str
    plan_name: str
    allowance_bytes: int
    audit_start: datetime | None
    bundle_expiry: datetime
    timezone: str
    status: Literal["draft", "active", "completed", "cancelled"]
    is_current: bool
