from __future__ import annotations

import plistlib
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from backend.app.config import Settings
from collector.service import (
    LABEL,
    LaunchAgentManager,
    ServiceConfigurationError,
    ServiceOwnershipError,
)


class FakeLaunchctl:
    def __init__(self) -> None:
        self.loaded = False
        self.running = False
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        values = list(command)
        self.commands.append(values)
        action = values[1]
        if action == "print":
            return subprocess.CompletedProcess(
                values,
                0 if self.loaded else 113,
                "state = running\n" if self.running else "state = waiting\n",
                "" if self.loaded else "not found",
            )
        if action in {"bootstrap", "kickstart"}:
            self.loaded = True
            self.running = True
        elif action == "bootout":
            self.loaded = False
            self.running = False
        return subprocess.CompletedProcess(values, 0, "", "")


def manager(tmp_path: Path, runner: FakeLaunchctl | None = None) -> LaunchAgentManager:
    return LaunchAgentManager(
        settings=Settings(
            database_path=tmp_path / "dachik-test.sqlite3",
            runtime_environment="test",
        ),
        python_executable=Path(sys.executable),
        repository_root=Path(__file__).resolve().parents[2],
        launch_agents_directory=tmp_path / "LaunchAgents",
        application_support_directory=tmp_path / "Application Support" / "Dachik",
        runner=runner or FakeLaunchctl(),
        uid=501,
    )


def test_configuration_uses_exact_python_module_and_safe_environment(tmp_path: Path) -> None:
    service = manager(tmp_path)
    configuration = service.configuration(
        interval_seconds=12.5,
        max_gap_seconds=45,
        requested_interface="en0",
    )

    assert configuration["Label"] == LABEL
    assert configuration["ProgramArguments"] == [
        str(Path(sys.executable).absolute()),
        "-m",
        "collector",
        "monitor",
        "--interval",
        "12.5",
        "--max-gap",
        "45",
        "--log-file",
        str(service.log_path),
        "--interface",
        "en0",
    ]
    environment = configuration["EnvironmentVariables"]
    assert isinstance(environment, dict)
    assert environment == {
        "DACHIK_DATABASE_PATH": str((tmp_path / "dachik-test.sqlite3").resolve()),
        "DACHIK_ENVIRONMENT": "test",
        "PYTHONUNBUFFERED": "1",
    }
    assert configuration["StandardOutPath"] == "/dev/null"
    assert configuration["StandardErrorPath"] == "/dev/null"


def test_install_is_isolated_idempotent_and_private(tmp_path: Path) -> None:
    service = manager(tmp_path)
    unrelated = service.launch_agents_directory / "com.example.unrelated.plist"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("unrelated")

    first = service.install()
    initial_payload = first.read_bytes()
    second = service.install()

    assert first == second
    assert second.read_bytes() == initial_payload
    assert first.stat().st_mode & 0o777 == 0o600
    assert unrelated.read_text() == "unrelated"
    assert plistlib.loads(first.read_bytes())["DachikManaged"] is True


def test_start_stop_restart_and_status_use_mocked_launchd(tmp_path: Path) -> None:
    launchctl = FakeLaunchctl()
    service = manager(tmp_path, launchctl)
    service.install()

    assert service.status().state == "stopped"
    assert service.start().process_running is True
    launchctl.running = False
    assert service.start().process_running is True
    assert service.restart().process_running is True
    assert service.stop().expected_to_run is False
    assert any(command[1] == "bootstrap" for command in launchctl.commands)
    assert any(command[1] == "kickstart" for command in launchctl.commands)
    assert any(command[1] == "bootout" for command in launchctl.commands)


def test_uninstall_removes_only_dachik_owned_configuration(tmp_path: Path) -> None:
    service = manager(tmp_path)
    unrelated = service.launch_agents_directory / "unrelated.plist"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep")
    service.install()

    service.uninstall()

    assert not service.plist_path.exists()
    assert unrelated.read_text() == "keep"


def test_uninstall_refuses_non_dachik_file(tmp_path: Path) -> None:
    service = manager(tmp_path)
    service.plist_path.parent.mkdir(parents=True)
    service.plist_path.write_bytes(plistlib.dumps({"Label": "not-dachik"}))

    with pytest.raises(ServiceOwnershipError):
        service.uninstall()


def test_unsafe_environment_and_database_combinations_are_refused(tmp_path: Path) -> None:
    real_launch_agents = Path.home() / "Library" / "LaunchAgents"
    test_service = LaunchAgentManager(
        settings=Settings(database_path=tmp_path / "test.sqlite3", runtime_environment="test"),
        python_executable=Path(sys.executable),
        repository_root=Path(__file__).resolve().parents[2],
        launch_agents_directory=real_launch_agents,
        application_support_directory=tmp_path,
        runner=FakeLaunchctl(),
    )
    with pytest.raises(ServiceConfigurationError, match="may not modify"):
        test_service.install()

    development_service = LaunchAgentManager(
        settings=Settings(
            database_path=tmp_path / "not-development.sqlite3",
            runtime_environment="development",
        ),
        python_executable=Path(sys.executable),
        repository_root=Path(__file__).resolve().parents[2],
        launch_agents_directory=tmp_path / "LaunchAgents",
        application_support_directory=tmp_path,
        runner=FakeLaunchctl(),
    )
    with pytest.raises(ServiceConfigurationError, match="normal Dachik development database"):
        development_service.install()
