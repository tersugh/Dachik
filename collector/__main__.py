"""Dachik collector command-line entry point."""

import argparse
import asyncio
from pathlib import Path

from backend.app.config import Settings
from backend.app.database import Database
from backend.app.services import DachikService
from collector.macos import MacOSTrafficProvider
from collector.monitor import monitor
from collector.service import LaunchAgentManager


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m collector")
    subparsers = parser.add_subparsers(dest="command", required=True)
    monitor_parser = subparsers.add_parser("monitor", help="measure macOS interface counters")
    monitor_parser.add_argument(
        "--interval", type=float, default=10.0, help="seconds between samples"
    )
    monitor_parser.add_argument(
        "--max-gap", type=float, default=30.0, help="largest trusted interval in seconds"
    )
    monitor_parser.add_argument("--interface", help="explicit physical en interface override")
    monitor_parser.add_argument("--samples", type=int, help="stop after this many samples")
    monitor_parser.add_argument("--log-file", type=Path, help="rotating diagnostic log path")
    service_parser = subparsers.add_parser("service", help="manage the background sensor")
    service_subparsers = service_parser.add_subparsers(dest="service_command", required=True)
    install_parser = service_subparsers.add_parser("install")
    install_parser.add_argument("--interval", type=float, default=10.0)
    install_parser.add_argument("--max-gap", type=float, default=30.0)
    install_parser.add_argument("--interface")
    for lifecycle_command in ("start", "stop", "restart", "status", "uninstall"):
        service_subparsers.add_parser(lifecycle_command)
    connection_parser = subparsers.add_parser(
        "connection", help="confirm the network associated with a legacy active audit"
    )
    connection_subparsers = connection_parser.add_subparsers(
        dest="connection_command", required=True
    )
    confirm_parser = connection_subparsers.add_parser("confirm")
    confirm_parser.add_argument("--interface", help="explicit physical en interface override")
    confirm_parser.add_argument(
        "--experiment-id",
        help="active audit to confirm when development data contains more than one",
    )
    args = parser.parse_args()
    if args.command == "service":
        return _service_command(args)
    if args.command == "connection":
        return _connection_command(args, parser)
    if args.interval <= 0 or args.max_gap <= 0:
        parser.error("interval and max-gap must be positive")
    if args.samples is not None and args.samples <= 0:
        parser.error("samples must be positive")
    try:
        asyncio.run(
            monitor(
                interval_seconds=args.interval,
                max_gap_seconds=args.max_gap,
                requested_interface=args.interface,
                sample_limit=args.samples,
                log_file=args.log_file,
            )
        )
    except KeyboardInterrupt:
        print("Dachik collector stopped cleanly")
        return 0
    except RuntimeError as exc:
        parser.error(str(exc))
    return 0


def _connection_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        provider = MacOSTrafficProvider(requested_interface=args.interface)
        database = Database(Settings().database_path)
        database.initialize()
        try:
            with database.session() as session:
                DachikService(session).confirm_active_audit_connection(
                    provider.interface_name,
                    provider.connection_fingerprint,
                    experiment_id=args.experiment_id,
                )
        finally:
            database.dispose()
    except RuntimeError as exc:
        parser.error(str(exc))
    print("Current connection confirmed for the active data plan.")
    return 0


def _service_command(args: argparse.Namespace) -> int:
    manager = LaunchAgentManager()
    command = str(args.service_command)
    if command == "install":
        path = manager.install(
            interval_seconds=args.interval,
            max_gap_seconds=args.max_gap,
            requested_interface=args.interface,
        )
        print(f"Dachik sensor service installed: {path}")
    elif command == "start":
        _print_status(manager.start())
    elif command == "stop":
        _print_status(manager.stop())
    elif command == "restart":
        _print_status(manager.restart())
    elif command == "status":
        _print_status(manager.status())
    elif command == "uninstall":
        manager.uninstall()
        print("Dachik sensor service uninstalled")
    return 0


def _print_status(status: object) -> None:
    from collector.service import ServiceStatus

    if not isinstance(status, ServiceStatus):
        raise TypeError("unexpected sensor service status")
    print(
        "Dachik sensor: "
        f"installed={'yes' if status.installed else 'no'}, "
        f"expected={'running' if status.expected_to_run else 'stopped'}, "
        f"process={status.state}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
