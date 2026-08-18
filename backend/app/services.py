"""Domain rules and transactional workflows for Dachik persistence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, NamedTuple

from sqlalchemy.orm import Session

from backend.app import models, schemas
from backend.app.repositories import Repository


class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ConnectionAttributionError(DomainError):
    pass


class MultipleActivePlansError(ConflictError):
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

MeasurementStatus = Literal[
    "no_active_plan",
    "multiple_active_plans",
    "waiting",
    "active",
    "paused",
    "interrupted",
    "unavailable",
    "ambiguous",
]


class SensorLifecycleState(NamedTuple):
    installed: bool
    expected_to_run: bool
    process_running: bool


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

    def active_experiments(self) -> list[models.DataAuditExperiment]:
        return [item for item in self.repository.list_experiments() if item.status == "active"]

    def current_experiment(self) -> models.DataAuditExperiment | None:
        active = self.active_experiments()
        target = self.repository.get_current_tracking_target()
        if target is not None:
            selected = self.repository.get_experiment(target.experiment_id)
            if selected is not None and selected.status == "active":
                return selected
        if len(active) == 1:
            return active[0]
        if len(active) > 1:
            raise MultipleActivePlansError(
                "More than one active data plan exists; choose which plan to track"
            )
        return None

    def select_current_experiment(self, experiment_id: str) -> models.DataAuditExperiment:
        experiment = self.get_experiment(experiment_id)
        if experiment.status != models.ExperimentStatus.ACTIVE.value:
            raise ConflictError("Only an active data plan can be selected for tracking")
        self.repository.select_tracking_target(experiment.id)
        return experiment

    def start_experiment(
        self, experiment_id: str, *, switch_current: bool = False
    ) -> models.DataAuditExperiment:
        experiment = self.get_experiment(experiment_id)
        if experiment.status != models.ExperimentStatus.DRAFT.value:
            raise ConflictError("Only a draft experiment can be started")
        try:
            current = self.current_experiment()
        except MultipleActivePlansError:
            if not switch_current:
                raise
            current = None
        if current is not None and current.id != experiment.id and not switch_current:
            raise ConflictError(
                "A data plan is already being tracked; confirm switching plans first"
            )
        experiment.status = models.ExperimentStatus.ACTIVE.value
        experiment.started_at = datetime.now(UTC)
        self.repository.select_tracking_target(experiment.id)
        return experiment

    def complete_experiment(self, experiment_id: str) -> models.DataAuditExperiment:
        experiment = self.get_experiment(experiment_id)
        if experiment.status != models.ExperimentStatus.ACTIVE.value:
            raise ConflictError("Only an active experiment can be completed")
        experiment.status = models.ExperimentStatus.COMPLETED.value
        experiment.ended_at = datetime.now(UTC)
        self.repository.clear_tracking_target(experiment.id)
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

    def ensure_interface_setup(
        self,
        interface_name: str,
        provider_version: str,
        connection_fingerprint: str | None = None,
    ) -> tuple[models.TrafficSource, models.CounterSeries, models.CounterSeries]:
        active_experiment = self.current_experiment()
        if active_experiment is not None:
            device = self.repository.get_device(active_experiment.device_id)
        else:
            macs = [
                item
                for item in self.repository.list_devices()
                if item.operating_system == "macOS"
            ]
            if len(macs) != 1:
                raise DomainError("Start a data plan or configure exactly one local Mac first")
            device = macs[0]
        if device is None:
            raise NotFoundError("Local Mac not found")
        expected_source: models.TrafficSource | None = None
        if active_experiment is not None and active_experiment.measurement_source_id is not None:
            expected_source = self.repository.get_source(active_experiment.measurement_source_id)
            expected_fingerprint = (
                expected_source.source_metadata.get("connection_fingerprint")
                if expected_source is not None and expected_source.source_metadata
                else None
            )
            if connection_fingerprint is not None and expected_fingerprint is not None:
                if connection_fingerprint != expected_fingerprint:
                    raise ConnectionAttributionError(
                        "The current network is not the connection bound to this active data plan"
                    )
            elif connection_fingerprint is not None and expected_source is not None:
                # Existing pre-attribution sources cannot be rebound silently: doing so
                # could attach another network's traffic to the active plan.
                raise ConnectionAttributionError(
                    "This existing audit has no trusted network identity; "
                    "attribution needs confirmation"
                )
        suffix = f":connection:{connection_fingerprint}" if connection_fingerprint else ""
        scope = f"external-interface:{interface_name}{suffix}"
        source = (
            expected_source
            if expected_source is not None
            and connection_fingerprint is not None
            and expected_source.source_metadata
            and expected_source.source_metadata.get("connection_fingerprint")
            == connection_fingerprint
            else self.repository.find_source(
                "macos-interface-counters", "macOS interface counters", scope
            )
        )
        if source is None:
            source = models.TrafficSource(
                provider_type="macos-interface-counters",
                domain="measured.interface",
                name="macOS interface counters",
                scope=scope,
                unit="bytes",
                monotonic=True,
                active=True,
                provider_version=provider_version,
                source_metadata={
                    "interface": interface_name,
                    "mechanism": "netstat-byte-counters",
                    "connection_fingerprint": connection_fingerprint,
                    "connection_identity_method": "wifi-ssid-and-default-gateway-sha256-v1"
                    if connection_fingerprint
                    else None,
                },
            )
            self.repository.add(source)
        download = self._ensure_interface_series(source, device, interface_name, "download")
        upload = self._ensure_interface_series(source, device, interface_name, "upload")
        if active_experiment is not None and active_experiment.measurement_source_id is None:
            active_experiment.measurement_source_id = source.id
        return source, download, upload

    def confirm_active_audit_connection(
        self,
        interface_name: str,
        connection_fingerprint: str,
        *,
        experiment_id: str | None = None,
    ) -> models.DataAuditExperiment:
        """Explicitly enrich a legacy audit source with an opaque connection identity."""
        active = self.active_experiments()
        if experiment_id is None:
            if len(active) != 1:
                raise ConflictError(
                    "Connection confirmation requires exactly one active audit "
                    "or an explicit audit ID"
                )
            experiment = active[0]
        else:
            selected_experiment = self.repository.get_experiment(experiment_id)
            if selected_experiment is None or selected_experiment.status != "active":
                raise NotFoundError("The selected active audit was not found")
            experiment = selected_experiment
        if experiment.measurement_source_id is None:
            candidates = {
                series.source_id
                for series in self.repository.interface_series_for_device(experiment.device_id)
                if series.identity == interface_name
            }
            if len(candidates) != 1:
                raise ConflictError(
                    "The legacy audit's historical measurement source is ambiguous"
                )
            experiment.measurement_source_id = next(iter(candidates))
        source = self.repository.get_source(experiment.measurement_source_id)
        if source is None or source.provider_type != "macos-interface-counters":
            raise DomainError("The active audit is not using a macOS interface source")
        metadata = dict(source.source_metadata or {})
        expected_interface = metadata.get("interface")
        if expected_interface != interface_name:
            raise ConnectionAttributionError(
                "The current physical interface differs from the audit's historical source"
            )
        existing = metadata.get("connection_fingerprint")
        if existing is not None and existing != connection_fingerprint:
            raise ConnectionAttributionError(
                "The active audit is already bound to a different connection"
            )
        metadata["connection_fingerprint"] = connection_fingerprint
        metadata["connection_identity_method"] = (
            "wifi-ssid-and-default-gateway-sha256-v1"
        )
        metadata["connection_confirmed_explicitly"] = True
        source.source_metadata = metadata
        return experiment

    def record_connection_unavailable(self, reason: str, *, at: datetime | None = None) -> None:
        """Preserve a known non-attributable boundary without inventing zero usage."""
        experiment = self.current_experiment()
        if experiment is None or experiment.measurement_source_id is None:
            return
        series = self.repository.interface_series_for_source(
            experiment.device_id, experiment.measurement_source_id
        )
        download = next((item for item in series if item.direction == "download"), None)
        latest = self.repository.latest_observation_for_source(experiment.measurement_source_id)
        end = at or datetime.now(UTC)
        if download is None or latest is None or end <= latest.timestamp_utc:
            return
        self._record_discontinuity(
            experiment, download, latest.timestamp_utc, end, reason
        )

    def _ensure_interface_series(
        self,
        source: models.TrafficSource,
        device: models.Device,
        interface_name: str,
        direction: str,
    ) -> models.CounterSeries:
        existing = self.repository.find_series(
            source.id, device.id, direction, interface_name, source.scope
        )
        if existing is not None:
            return existing
        series = models.CounterSeries(
            source_id=source.id,
            device_id=device.id,
            direction=direction,
            identity=interface_name,
            accounting_domain="measured.interface",
            scope=source.scope,
        )
        self.repository.add(series)
        return series

    def record_interface_observation(
        self,
        data: schemas.InterfaceObservationCreate,
        *,
        max_gap: timedelta,
    ) -> tuple[models.CounterObservation, models.CounterObservation, bool]:
        download_series = self.repository.get_series(data.download.counter_series_id)
        upload_series = self.repository.get_series(data.upload.counter_series_id)
        if download_series is None or upload_series is None:
            raise NotFoundError("Counter series not found")
        if (
            download_series.direction != "download"
            or upload_series.direction != "upload"
            or download_series.source_id != upload_series.source_id
            or download_series.device_id != upload_series.device_id
            or download_series.identity != upload_series.identity
        ):
            raise DomainError("Interface observations must use compatible download/upload series")

        previous_download = self.repository.previous_observation(
            download_series.id, data.download.timestamp_utc
        )
        previous_upload = self.repository.previous_observation(
            upload_series.id, data.upload.timestamp_utc
        )
        latest_device_observation = self.repository.latest_observation_for_device(
            download_series.device_id
        )
        download, download_created = self.record_observation(data.download)
        upload, upload_created = self.record_observation(data.upload)
        if download_created != upload_created:
            raise ConflictError("Paired observation was only partially idempotent")
        if not download_created:
            return download, upload, False

        active_experiment = self.current_experiment()
        if (
            active_experiment is not None
            and active_experiment.device_id != download_series.device_id
        ):
            active_experiment = None
        if active_experiment is not None:
            if active_experiment.measurement_source_id is None:
                active_experiment.measurement_source_id = download_series.source_id
            elif active_experiment.measurement_source_id != download_series.source_id:
                expected_latest = self.repository.latest_observation_for_source(
                    active_experiment.measurement_source_id
                )
                if (
                    expected_latest is not None
                    and expected_latest.timestamp_utc < download.timestamp_utc
                ):
                    expected_series = self.repository.get_series(
                        expected_latest.counter_series_id
                    )
                    self._record_discontinuity(
                        active_experiment,
                        download_series,
                        expected_latest.timestamp_utc,
                        download.timestamp_utc,
                        "interface_changed"
                        if expected_series is not None
                        and expected_series.identity != download_series.identity
                        else "connection_changed",
                    )
                return download, upload, True
        if previous_download is None and previous_upload is None:
            if (
                active_experiment is not None
                and active_experiment.started_at is not None
                and download.timestamp_utc - active_experiment.started_at > max_gap
            ):
                self._record_discontinuity(
                    active_experiment,
                    download_series,
                    active_experiment.started_at,
                    download.timestamp_utc,
                    "measurement_gap",
                )
            if latest_device_observation is not None:
                previous_series = self.repository.get_series(
                    latest_device_observation.counter_series_id
                )
                if (
                    previous_series is not None
                    and previous_series.identity != download_series.identity
                    and latest_device_observation.timestamp_utc < download.timestamp_utc
                ):
                    self._record_discontinuity(
                        active_experiment,
                        download_series,
                        latest_device_observation.timestamp_utc,
                        download.timestamp_utc,
                        "interface_changed",
                    )
            return download, upload, True
        if previous_download is None or previous_upload is None:
            raise DomainError("Download/upload observation history is inconsistent")

        reason = self._continuity_failure_reason(
            previous_download, previous_upload, download, upload, max_gap
        )
        if reason is not None:
            self._record_discontinuity(
                active_experiment,
                download_series,
                previous_download.timestamp_utc,
                download.timestamp_utc,
                reason,
            )
            return download, upload, True

        self.repository.add(
            models.UsageInterval(
                counter_series_id=download_series.id,
                start_timestamp=previous_download.timestamp_utc,
                end_timestamp=download.timestamp_utc,
                delta_bytes=download.raw_counter_bytes - previous_download.raw_counter_bytes,
                quality="accepted",
                methodology_version="interface-delta-v1",
            )
        )
        self.repository.add(
            models.UsageInterval(
                counter_series_id=upload_series.id,
                start_timestamp=previous_upload.timestamp_utc,
                end_timestamp=upload.timestamp_utc,
                delta_bytes=upload.raw_counter_bytes - previous_upload.raw_counter_bytes,
                quality="accepted",
                methodology_version="interface-delta-v1",
            )
        )
        return download, upload, True

    @staticmethod
    def _continuity_failure_reason(
        previous_download: models.CounterObservation,
        previous_upload: models.CounterObservation,
        download: models.CounterObservation,
        upload: models.CounterObservation,
        max_gap: timedelta,
    ) -> str | None:
        if (
            download.session_id != previous_download.session_id
            or upload.session_id != previous_upload.session_id
        ):
            previous_boot = previous_download.session_id.split("/", 1)[0]
            current_boot = download.session_id.split("/", 1)[0]
            return "system_reboot" if previous_boot != current_boot else "collector_session_changed"
        if (
            download.monotonic_timestamp_ns <= previous_download.monotonic_timestamp_ns
            or upload.monotonic_timestamp_ns <= previous_upload.monotonic_timestamp_ns
        ):
            return "invalid_monotonic_time"
        if download.timestamp_utc - previous_download.timestamp_utc > max_gap:
            return "measurement_gap"
        if (
            download.raw_counter_bytes < previous_download.raw_counter_bytes
            or upload.raw_counter_bytes < previous_upload.raw_counter_bytes
        ):
            return "counter_reset"
        return None

    def _record_discontinuity(
        self,
        experiment: models.DataAuditExperiment | None,
        series: models.CounterSeries,
        start: datetime,
        end: datetime,
        reason: str,
    ) -> None:
        self.repository.add(
            models.MeasurementDiscontinuity(
                experiment_id=experiment.id if experiment else None,
                counter_series_id=series.id,
                source_id=series.source_id,
                start_timestamp=start,
                end_timestamp=end,
                reason=reason,
                details="No usage was derived across this continuity boundary.",
            )
        )

    def start_collector_run(
        self, source_id: str | None, health_metadata: dict[str, object] | None = None
    ) -> models.CollectorRun:
        run = models.CollectorRun(
            source_id=source_id,
            started_at=datetime.now(UTC),
            collector_version="0.1.0",
            status="running",
            health_metadata=health_metadata,
        )
        self.repository.add(run)
        return run

    def finish_collector_run(
        self, run_id: str, status: str, error_code: str | None = None
    ) -> None:
        run = self.repository.session.get(models.CollectorRun, run_id)
        if run is None:
            raise NotFoundError("Collector run not found")
        run.status = status
        run.error_code = error_code
        run.ended_at = datetime.now(UTC)

    def current_experiment_usage(
        self,
        *,
        now: datetime | None = None,
        stale_after: timedelta = timedelta(seconds=60),
        lifecycle: SensorLifecycleState | None = None,
    ) -> schemas.CurrentExperimentUsageResponse:
        current_time = now or datetime.now(UTC)
        latest_run = self.repository.latest_collector_run()
        try:
            experiment = self.current_experiment()
        except MultipleActivePlansError:
            return schemas.CurrentExperimentUsageResponse(
                experiment_id=None,
                status="multiple_active_plans",
                tracking_started_at=None,
                as_of_timestamp=current_time,
                latest_observation_at=None,
                observed_rx_bytes=None,
                observed_tx_bytes=None,
                total_observed_bytes=None,
                tracking_baseline_bytes=None,
                latest_provider_balance_bytes=None,
                accounted_remainder_bytes=None,
                covered_duration_seconds=0,
                eligible_duration_seconds=0,
                coverage_percent=None,
                known_inactive_duration_seconds=0,
                unknown_duration_seconds=0,
                has_coverage_gaps=False,
                has_unknown_gaps=False,
                interface_name=None,
                service_installed=lifecycle.installed if lifecycle else False,
                service_expected_to_run=lifecycle.expected_to_run if lifecycle else False,
                collector_run_status=latest_run.status if latest_run else None,
                message="Dachik found more than one active data plan. Choose which one to track.",
            )
        if experiment is None or experiment.started_at is None:
            return schemas.CurrentExperimentUsageResponse(
                experiment_id=None,
                status="no_active_plan",
                tracking_started_at=None,
                as_of_timestamp=current_time,
                latest_observation_at=None,
                observed_rx_bytes=None,
                observed_tx_bytes=None,
                total_observed_bytes=None,
                tracking_baseline_bytes=None,
                latest_provider_balance_bytes=None,
                accounted_remainder_bytes=None,
                covered_duration_seconds=0,
                eligible_duration_seconds=0,
                coverage_percent=None,
                known_inactive_duration_seconds=0,
                unknown_duration_seconds=0,
                has_coverage_gaps=False,
                has_unknown_gaps=False,
                interface_name=None,
                service_installed=lifecycle.installed if lifecycle else False,
                service_expected_to_run=lifecycle.expected_to_run if lifecycle else False,
                collector_run_status=latest_run.status if latest_run else None,
                message="No active data plan is being tracked.",
            )
        bundle = self.repository.get_bundle(experiment.data_bundle_id)
        if bundle is None:
            raise NotFoundError("Data bundle not found")
        window_start = max(experiment.started_at, bundle.billing_cycle_start)
        end = min(current_time, experiment.ended_at or current_time, bundle.billing_cycle_end)
        if end < window_start:
            end = window_start
        latest = self.repository.latest_observation_for_source(experiment.measurement_source_id)
        series = self.repository.interface_series_for_source(
            experiment.device_id, experiment.measurement_source_id
        )
        interface_name = None
        if latest is not None:
            latest_series = self.repository.get_series(latest.counter_series_id)
            interface_name = latest_series.identity if latest_series else None
        status, message = self._measurement_status(latest, current_time, stale_after)
        if (
            latest_run is not None
            and latest_run.status == "unavailable"
            and (latest is None or latest_run.started_at > latest.timestamp_utc)
        ):
            if latest_run.error_code == "InterfaceAmbiguityError":
                status = "ambiguous"
                message = "Dachik could not safely choose one network interface."
            else:
                status, message = "unavailable", "The measurement sensor is unavailable."
        elif (
            latest_run is not None
            and latest_run.status == "stopped"
            and latest_run.ended_at is not None
            and (latest is None or latest_run.ended_at >= latest.timestamp_utc)
        ):
            status, message = "interrupted", "Tracking is currently paused."
        if lifecycle is not None and lifecycle.installed and not lifecycle.expected_to_run:
            status, message = "paused", "Tracking is currently paused."
        elif (
            lifecycle is not None
            and lifecycle.expected_to_run
            and not lifecycle.process_running
            and status not in {"unavailable", "ambiguous"}
        ):
            status, message = "waiting", "The measurement sensor is starting."
        intervals = self.repository.usage_intervals(
            [item.id for item in series], window_start, end
        )
        series_by_id = {item.id: item for item in series}
        download_intervals = sorted(
            (
                item
                for item in intervals
                if series_by_id[item.counter_series_id].direction == "download"
            ),
            key=lambda item: item.start_timestamp,
        )
        overlapping_ids: set[str] = set()
        for previous, current in zip(download_intervals, download_intervals[1:], strict=False):
            if current.start_timestamp < previous.end_timestamp:
                overlapping_ids.update((previous.id, current.id))
        trusted_download = [item for item in download_intervals if item.id not in overlapping_ids]
        trusted_keys = {
            (
                series_by_id[item.counter_series_id].identity,
                item.start_timestamp,
                item.end_timestamp,
            )
            for item in trusted_download
        }
        trusted_intervals = [
            item
            for item in intervals
            if (
                series_by_id[item.counter_series_id].identity,
                item.start_timestamp,
                item.end_timestamp,
            )
            in trusted_keys
        ]
        rx = sum(
            item.delta_bytes
            for item in trusted_intervals
            if series_by_id[item.counter_series_id].direction == "download"
        )
        tx = sum(
            item.delta_bytes
            for item in trusted_intervals
            if series_by_id[item.counter_series_id].direction == "upload"
        )
        covered_seconds = self._union_duration_seconds(trusted_download)
        eligible_seconds = max(0, int((end - window_start).total_seconds()))
        coverage = (
            round(covered_seconds / eligible_seconds * 100, 1) if eligible_seconds else None
        )
        gaps = self.repository.discontinuities(experiment.id, window_start, end)
        known_inactive = [item for item in gaps if item.reason == "connection_changed"]
        unknown_gaps = [item for item in gaps if item.reason != "connection_changed"]
        known_inactive_seconds = self._union_ranges_seconds(
            [(item.start_timestamp, item.end_timestamp) for item in known_inactive]
        )
        unknown_seconds = self._union_ranges_seconds(
            [(item.start_timestamp, item.end_timestamp) for item in unknown_gaps]
        )
        usage_known = bool(trusted_download)
        initial_balance = self.repository.initial_remaining_balance(experiment.id)
        latest_balance = self.repository.latest_remaining_balance(experiment.id, end)
        tracking_baseline = (
            initial_balance.normalized_bytes if initial_balance is not None else None
        )
        total_observed = rx + tx if usage_known else None
        accounted_remainder = (
            max(0, tracking_baseline - total_observed)
            if tracking_baseline is not None and total_observed is not None
            else None
        )
        return schemas.CurrentExperimentUsageResponse(
            experiment_id=experiment.id,
            status=status,
            tracking_started_at=experiment.started_at,
            as_of_timestamp=end,
            latest_observation_at=latest.timestamp_utc if latest else None,
            observed_rx_bytes=rx if usage_known else None,
            observed_tx_bytes=tx if usage_known else None,
            total_observed_bytes=total_observed,
            tracking_baseline_bytes=tracking_baseline,
            latest_provider_balance_bytes=(
                latest_balance.normalized_bytes if latest_balance is not None else None
            ),
            accounted_remainder_bytes=accounted_remainder,
            covered_duration_seconds=covered_seconds,
            eligible_duration_seconds=eligible_seconds,
            coverage_percent=coverage,
            known_inactive_duration_seconds=known_inactive_seconds,
            unknown_duration_seconds=unknown_seconds,
            has_coverage_gaps=bool(unknown_gaps) or bool(overlapping_ids),
            has_unknown_gaps=bool(unknown_gaps) or bool(overlapping_ids),
            interface_name=interface_name,
            service_installed=lifecycle.installed if lifecycle else False,
            service_expected_to_run=lifecycle.expected_to_run if lifecycle else False,
            collector_run_status=latest_run.status if latest_run else None,
            message=message,
        )

    def measurement_status(
        self, *, lifecycle: SensorLifecycleState | None = None
    ) -> schemas.MeasurementStatusResponse:
        usage = self.current_experiment_usage(lifecycle=lifecycle)
        return schemas.MeasurementStatusResponse(
            status=usage.status,
            latest_observation_at=usage.latest_observation_at,
            interface_name=usage.interface_name,
            service_installed=usage.service_installed,
            service_expected_to_run=usage.service_expected_to_run,
            collector_run_status=usage.collector_run_status,
            message=usage.message,
        )

    @staticmethod
    def _measurement_status(
        latest: models.CounterObservation | None, now: datetime, stale_after: timedelta
    ) -> tuple[MeasurementStatus, str]:
        if latest is None:
            return "waiting", "Waiting for the first measurement."
        if now - latest.timestamp_utc > stale_after:
            return "interrupted", "Tracking is currently paused."
        return "active", "Dachik is observing this Mac."

    @staticmethod
    def _union_duration_seconds(intervals: list[models.UsageInterval]) -> int:
        return DachikService._union_ranges_seconds(
            [(item.start_timestamp, item.end_timestamp) for item in intervals]
        )

    @staticmethod
    def _union_ranges_seconds(ranges: list[tuple[datetime, datetime]]) -> int:
        ranges = sorted(ranges)
        if not ranges:
            return 0
        total = timedelta()
        current_start, current_end = ranges[0]
        for start, end in ranges[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                total += current_end - current_start
                current_start, current_end = start, end
        total += current_end - current_start
        return max(0, int(total.total_seconds()))

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
