"""Development sampling loop for macOS interface counters."""

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.app import schemas
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.services import ConnectionAttributionError as DomainAttributionError
from backend.app.services import DachikService, MultipleActivePlansError
from collector.macos import (
    ConnectionAttributionError,
    InterfaceSelectionError,
    MacOSTrafficProvider,
)

COLLECTOR_VERSION = "0.1.0"
LOGGER = logging.getLogger("dachik.collector")


def configure_logging(log_file: Path | None) -> None:
    if log_file is None:
        return
    log_file = log_file.expanduser().resolve()
    log_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3)
    log_file.chmod(0o600)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.disabled = False
    LOGGER.propagate = False


async def monitor(
    *,
    interval_seconds: float,
    max_gap_seconds: float,
    requested_interface: str | None = None,
    sample_limit: int | None = None,
    log_file: Path | None = None,
) -> None:
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    signal_handler_installed = False
    try:
        loop.add_signal_handler(signal.SIGTERM, stop_requested.set)
        signal_handler_installed = True
    except (NotImplementedError, RuntimeError):
        pass
    database = Database(Settings().database_path)
    database.initialize()
    configure_logging(log_file)
    run_id: str | None = None
    try:
        provider = MacOSTrafficProvider(requested_interface=requested_interface)
        with database.session() as session:
            service = DachikService(session)
            source, download, upload = service.ensure_interface_setup(
                provider.interface_name,
                provider.VERSION,
                provider.connection_fingerprint,
            )
            run = service.start_collector_run(
                source.id, {"interface": provider.interface_name, "mechanism": "netstat -bI"}
            )
            run_id = run.id
            download_id = download.id
            upload_id = upload.id
        message = f"Dachik measuring {provider.interface_name} with cumulative byte counters"
        print(message)
        LOGGER.info(message)
        sequence = 0
        while not stop_requested.is_set() and (
            sample_limit is None or sequence < sample_limit
        ):
            observation = (await provider.observe())[0]
            sequence += 1
            payload = schemas.InterfaceObservationCreate(
                download=schemas.CounterObservationCreate(
                    counter_series_id=download_id,
                    timestamp_utc=observation.observed_at,
                    monotonic_timestamp_ns=observation.monotonic_ns,
                    raw_counter_bytes=observation.rx_bytes,
                    session_id=observation.session_id,
                    sequence_key=str(sequence),
                    collector_version=COLLECTOR_VERSION,
                ),
                upload=schemas.CounterObservationCreate(
                    counter_series_id=upload_id,
                    timestamp_utc=observation.observed_at,
                    monotonic_timestamp_ns=observation.monotonic_ns,
                    raw_counter_bytes=observation.tx_bytes,
                    session_id=observation.session_id,
                    sequence_key=str(sequence),
                    collector_version=COLLECTOR_VERSION,
                ),
            )
            with database.session() as session:
                DachikService(session).record_interface_observation(
                    payload, max_gap=timedelta(seconds=max_gap_seconds)
                )
            LOGGER.debug("Persisted cumulative observation for %s", provider.interface_name)
            if sample_limit is None or sequence < sample_limit:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_requested.wait(), timeout=interval_seconds)
    except KeyboardInterrupt:
        pass
    except (InterfaceSelectionError, DomainAttributionError, MultipleActivePlansError) as exc:
        with database.session() as session:
            service = DachikService(session)
            if isinstance(exc, ConnectionAttributionError | DomainAttributionError):
                service.record_connection_unavailable("connection_changed")
            if run_id is None:
                run = service.start_collector_run(None, {"environment": "macOS"})
                service.finish_collector_run(run.id, "unavailable", type(exc).__name__)
        if run_id is not None:
            with database.session() as session:
                DachikService(session).finish_collector_run(
                    run_id, "unavailable", type(exc).__name__
                )
            run_id = None
        raise
    except Exception as exc:
        LOGGER.exception("Collector failed")
        if run_id is not None:
            with database.session() as session:
                DachikService(session).finish_collector_run(
                    run_id, "failed", type(exc).__name__
                )
            run_id = None
        raise
    finally:
        if run_id is not None:
            with database.session() as session:
                DachikService(session).finish_collector_run(run_id, "stopped")
            LOGGER.info("Collector stopped")
        database.dispose()
        if signal_handler_installed:
            loop.remove_signal_handler(signal.SIGTERM)
