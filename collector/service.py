"""Safe user-level launchd lifecycle for the development collector."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from backend.app.config import (
    BROWSER_VERIFICATION_ENVIRONMENT,
    DEFAULT_DATABASE_PATH,
    Settings,
)

LABEL: Final = "io.dachik.collector.development"
PLIST_NAME: Final = f"{LABEL}.plist"
TEST_ENVIRONMENT: Final = "test"


class ServiceConfigurationError(RuntimeError):
    """Raised when a service operation would use an unsafe configuration."""


class ServiceOwnershipError(RuntimeError):
    """Raised when an existing launch configuration is not Dachik-owned."""


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    installed: bool
    expected_to_run: bool
    process_running: bool
    state: str


class LaunchAgentManager:
    """Generate and manage Dachik's per-user development LaunchAgent."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        python_executable: Path | None = None,
        repository_root: Path | None = None,
        launch_agents_directory: Path | None = None,
        application_support_directory: Path | None = None,
        runner: CommandRunner = _run,
        uid: int | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.python_executable = (
            python_executable or Path(sys.executable)
        ).expanduser().absolute()
        self.repository_root = (
            repository_root or Path(__file__).resolve().parents[1]
        ).resolve()
        self.launch_agents_directory = (
            launch_agents_directory or Path.home() / "Library" / "LaunchAgents"
        ).resolve()
        self.application_support_directory = (
            application_support_directory
            or Path.home() / "Library" / "Application Support" / "Dachik"
        ).resolve()
        self.runner = runner
        self.uid = uid if uid is not None else os.getuid()

    @property
    def plist_path(self) -> Path:
        return self.launch_agents_directory / PLIST_NAME

    @property
    def domain_target(self) -> str:
        return f"gui/{self.uid}"

    @property
    def service_target(self) -> str:
        return f"{self.domain_target}/{LABEL}"

    @property
    def log_path(self) -> Path:
        return self.application_support_directory / "logs" / "collector.log"

    def configuration(
        self,
        *,
        interval_seconds: float = 10.0,
        max_gap_seconds: float = 30.0,
        requested_interface: str | None = None,
    ) -> dict[str, object]:
        self._validate_configuration(for_mutation=True, require_runtime=True)
        if interval_seconds <= 0 or max_gap_seconds <= 0:
            raise ServiceConfigurationError("interval and max-gap must be positive")
        arguments = [
            str(self.python_executable),
            "-m",
            "collector",
            "monitor",
            "--interval",
            str(interval_seconds),
            "--max-gap",
            str(max_gap_seconds),
            "--log-file",
            str(self.log_path),
        ]
        if requested_interface:
            if not requested_interface.startswith("en") or not requested_interface[2:].isdigit():
                raise ServiceConfigurationError(
                    "interface override must be a physical en interface"
                )
            arguments.extend(("--interface", requested_interface))
        return {
            "Label": LABEL,
            "DachikManaged": True,
            "ProgramArguments": arguments,
            "WorkingDirectory": str(self.repository_root),
            "EnvironmentVariables": {
                "DACHIK_DATABASE_PATH": str(self.settings.database_path.expanduser().resolve()),
                "DACHIK_ENVIRONMENT": self.settings.runtime_environment,
                "PYTHONUNBUFFERED": "1",
            },
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 300,
            "ProcessType": "Background",
            "StandardOutPath": "/dev/null",
            "StandardErrorPath": "/dev/null",
        }

    def install(
        self,
        *,
        interval_seconds: float = 10.0,
        max_gap_seconds: float = 30.0,
        requested_interface: str | None = None,
    ) -> Path:
        configuration = self.configuration(
            interval_seconds=interval_seconds,
            max_gap_seconds=max_gap_seconds,
            requested_interface=requested_interface,
        )
        payload = plistlib.dumps(configuration, fmt=plistlib.FMT_XML, sort_keys=True)
        if self.plist_path.exists():
            self._require_owned_plist()
            if self.plist_path.read_bytes() == payload:
                return self.plist_path
        self.launch_agents_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_path = self.plist_path.with_suffix(".plist.tmp")
        temporary_path.write_bytes(payload)
        temporary_path.chmod(0o600)
        temporary_path.replace(self.plist_path)
        return self.plist_path

    def start(self) -> ServiceStatus:
        self._validate_configuration(for_mutation=True, require_runtime=True)
        self._require_owned_plist(validate_launch=True)
        current = self.status()
        if not current.expected_to_run:
            result = self.runner(
                ["/bin/launchctl", "bootstrap", self.domain_target, str(self.plist_path)]
            )
            self._require_success(result, "start Dachik sensor")
        elif not current.process_running:
            result = self.runner(["/bin/launchctl", "kickstart", self.service_target])
            self._require_success(result, "start Dachik sensor")
        return self.status()

    def stop(self) -> ServiceStatus:
        self._validate_configuration(for_mutation=True, require_runtime=False)
        if self.status().expected_to_run:
            result = self.runner(["/bin/launchctl", "bootout", self.service_target])
            self._require_success(result, "stop Dachik sensor")
            return self._wait_until_unloaded()
        return self.status()

    def restart(self) -> ServiceStatus:
        self.stop()
        return self.start()

    def uninstall(self) -> None:
        self._validate_configuration(for_mutation=True, require_runtime=False)
        if not self.plist_path.exists():
            return
        self._require_owned_plist()
        self.stop()
        self.plist_path.unlink()

    def status(self) -> ServiceStatus:
        installed = self.plist_path.is_file()
        result = self.runner(["/bin/launchctl", "print", self.service_target])
        loaded = result.returncode == 0
        output = result.stdout.lower()
        running = loaded and "state = running" in output
        state = "running" if running else "starting" if loaded else "stopped"
        return ServiceStatus(
            installed=installed,
            expected_to_run=loaded,
            process_running=running,
            state=state,
        )

    def _wait_until_unloaded(self, timeout_seconds: float = 5.0) -> ServiceStatus:
        deadline = time.monotonic() + timeout_seconds
        current = self.status()
        while current.expected_to_run and time.monotonic() < deadline:
            time.sleep(0.1)
            current = self.status()
        if current.expected_to_run:
            raise RuntimeError("Could not stop Dachik sensor: launchd did not unload it")
        return current

    def _validate_configuration(self, *, for_mutation: bool, require_runtime: bool) -> None:
        database_path = self.settings.database_path.expanduser().resolve()
        normal_database = DEFAULT_DATABASE_PATH.expanduser().resolve()
        if require_runtime:
            if not self.python_executable.is_file():
                raise ServiceConfigurationError("Dachik Python executable does not exist")
            if not (self.repository_root / "collector" / "__main__.py").is_file():
                raise ServiceConfigurationError("Dachik repository path is invalid")
        if self.settings.runtime_environment == "development" and database_path != normal_database:
            raise ServiceConfigurationError(
                "Development sensor service must use the normal Dachik development database"
            )
        real_launch_agents = (Path.home() / "Library" / "LaunchAgents").resolve()
        if (
            for_mutation
            and self.settings.runtime_environment
            in {TEST_ENVIRONMENT, BROWSER_VERIFICATION_ENVIRONMENT}
            and self.launch_agents_directory == real_launch_agents
        ):
            raise ServiceConfigurationError(
                "Tests and browser verification may not modify the real LaunchAgents directory"
            )
        if (
            self.settings.runtime_environment == BROWSER_VERIFICATION_ENVIRONMENT
            and database_path == normal_database
        ):
            raise ServiceConfigurationError(
                "Browser verification must not use the normal Dachik development database"
            )

    def _require_owned_plist(self, *, validate_launch: bool = False) -> dict[str, object]:
        if not self.plist_path.is_file():
            raise ServiceConfigurationError("Dachik sensor service is not installed")
        try:
            contents = cast(dict[str, object], plistlib.loads(self.plist_path.read_bytes()))
        except (OSError, plistlib.InvalidFileException) as exc:
            raise ServiceOwnershipError("Existing service file is not a valid plist") from exc
        if contents.get("Label") != LABEL or contents.get("DachikManaged") is not True:
            raise ServiceOwnershipError("Refusing to modify a service file not owned by Dachik")
        if validate_launch:
            arguments = contents.get("ProgramArguments")
            environment = contents.get("EnvironmentVariables")
            expected_prefix = [str(self.python_executable), "-m", "collector", "monitor"]
            if not isinstance(arguments, list) or arguments[:4] != expected_prefix:
                raise ServiceOwnershipError("Refusing to launch an altered Dachik service file")
            if not isinstance(environment, dict) or environment.get(
                "DACHIK_DATABASE_PATH"
            ) != str(self.settings.database_path.expanduser().resolve()):
                raise ServiceOwnershipError("Refusing to launch a service for another database")
            if environment.get("DACHIK_ENVIRONMENT") != self.settings.runtime_environment:
                raise ServiceOwnershipError("Refusing to launch a service for another environment")
        return contents

    @staticmethod
    def _require_success(result: subprocess.CompletedProcess[str], action: str) -> None:
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "launchctl failed"
            raise RuntimeError(f"Could not {action}: {detail}")
