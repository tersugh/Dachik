"""Privacy-safe macOS cumulative interface byte counters."""

import asyncio
import hashlib
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from collector.models import RawTrafficObservation, TrafficDomain

CommandRunner = Callable[[Sequence[str]], str]


class InterfaceSelectionError(RuntimeError):
    """The authoritative external interface cannot be selected safely."""


class InterfaceAmbiguityError(InterfaceSelectionError):
    """More than one plausible default interface was found."""


class InterfaceUnavailableError(InterfaceSelectionError):
    """No supported active external interface is available."""


class ConnectionAttributionError(InterfaceSelectionError):
    """The current network cannot be attributed to the audited connection."""


def run_command(command: Sequence[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout


class MacOSInterfaceSelector:
    """Select one active physical interface from the IPv4 default route."""

    def __init__(self, runner: CommandRunner = run_command, requested: str | None = None) -> None:
        self._runner = runner
        self._requested = requested

    def select(self) -> str:
        candidates = {self._requested} if self._requested else self._default_route_interfaces()
        candidates.discard(None)
        if not candidates:
            raise InterfaceUnavailableError("No default network interface is available")
        if len(candidates) > 1:
            raise InterfaceAmbiguityError(
                f"Multiple default network interfaces are active: {', '.join(sorted(candidates))}"
            )
        interface = next(iter(candidates))
        if not re.fullmatch(r"en\d+", interface):
            raise InterfaceUnavailableError(
                f"Default interface {interface} is virtual or unsupported; "
                "choose a physical en interface"
            )
        details = self._runner(["/sbin/ifconfig", interface])
        first_line = details.splitlines()[0] if details.splitlines() else ""
        if "UP" not in first_line or "RUNNING" not in first_line or "status: active" not in details:
            raise InterfaceUnavailableError(f"Interface {interface} is not active")
        return interface

    def _default_route_interfaces(self) -> set[str]:
        output = self._runner(["/usr/sbin/netstat", "-rn", "-f", "inet"])
        lines = [line.split() for line in output.splitlines() if line.strip()]
        header = next((tokens for tokens in lines if tokens and tokens[0] == "Destination"), None)
        if header is None or "Netif" not in header:
            raise InterfaceUnavailableError("macOS routing output did not contain a Netif column")
        interface_index = header.index("Netif")
        return {
            tokens[interface_index]
            for tokens in lines
            if len(tokens) > interface_index and tokens[0] == "default"
        }


class MacOSTrafficProvider:
    """Emit cumulative RX/TX bytes for one selected macOS interface."""

    VERSION = "netstat-v1"

    def __init__(
        self,
        *,
        runner: CommandRunner = run_command,
        requested_interface: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self._runner = runner
        self._selector = MacOSInterfaceSelector(runner, requested_interface)
        self.interface_name = self._selector.select()
        self.connection_fingerprint = self._read_connection_fingerprint()
        self._boot_id = self._read_boot_id()
        self._run_id = run_id or str(uuid.uuid4())

    @property
    def provider_id(self) -> str:
        return f"macos-interface:{self.interface_name}"

    @property
    def session_id(self) -> str:
        return f"{self._boot_id}/{self._run_id}"

    async def observe(self) -> tuple[RawTrafficObservation, ...]:
        try:
            return (await asyncio.to_thread(self._observe_sync),)
        except subprocess.CalledProcessError as exc:
            raise InterfaceUnavailableError(
                f"macOS interface command failed: {exc.cmd[0]}"
            ) from exc

    def _observe_sync(self) -> RawTrafficObservation:
        current_interface = self._selector.select()
        if current_interface != self.interface_name:
            raise InterfaceSelectionError(
                f"Default interface changed from {self.interface_name} to {current_interface}"
            )
        if self._read_connection_fingerprint() != self.connection_fingerprint:
            raise ConnectionAttributionError(
                "Network connection changed; traffic attribution was stopped"
            )
        rx_bytes, tx_bytes = self._read_counters()
        return RawTrafficObservation(
            provider_id=self.provider_id,
            series_id=self.interface_name,
            domain=TrafficDomain.INTERFACE,
            observed_at=datetime.now(UTC),
            monotonic_ns=time.monotonic_ns(),
            session_id=self.session_id,
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
        )

    def _read_boot_id(self) -> str:
        for key in ("kern.bootsessionuuid", "kern.boottime"):
            try:
                value = self._runner(["/usr/sbin/sysctl", "-n", key]).strip()
            except subprocess.CalledProcessError:
                continue
            if value:
                return re.sub(r"\s+", "-", value)
        raise InterfaceUnavailableError("macOS boot identity is unavailable")

    def _read_counters(self) -> tuple[int, int]:
        output = self._runner(["/usr/sbin/netstat", "-bI", self.interface_name])
        rows = [line.split() for line in output.splitlines() if line.strip()]
        header = next((tokens for tokens in rows if tokens and tokens[0] == "Name"), None)
        if header is None or "Ibytes" not in header or "Obytes" not in header:
            raise InterfaceUnavailableError("macOS counter output is missing byte columns")
        ibytes_index = header.index("Ibytes")
        obytes_index = header.index("Obytes")
        link_rows = [
            tokens
            for tokens in rows
            if len(tokens) > max(ibytes_index, obytes_index)
            and tokens[0] == self.interface_name
            and len(tokens) > 2
            and tokens[2].startswith("<Link#")
        ]
        if len(link_rows) != 1:
            raise InterfaceUnavailableError(
                f"Expected one link-counter row for {self.interface_name}, found {len(link_rows)}"
            )
        try:
            rx_bytes = int(link_rows[0][ibytes_index])
            tx_bytes = int(link_rows[0][obytes_index])
        except ValueError as exc:
            raise InterfaceUnavailableError("macOS byte counters were not integers") from exc
        if rx_bytes < 0 or tx_bytes < 0:
            raise InterfaceUnavailableError("macOS returned negative byte counters")
        return rx_bytes, tx_bytes

    def _read_connection_fingerprint(self) -> str:
        """Return an opaque identity for the associated Wi-Fi network.

        The SSID is used only in memory and is never persisted or logged. Combining
        it with the default gateway distinguishes ordinary network changes while
        avoiding browsing or destination data. If macOS cannot expose both values,
        attribution is conservatively unavailable.
        """
        output = self._runner(["/usr/sbin/networksetup", "-getairportnetwork", self.interface_name])
        prefix = "Current Wi-Fi Network: "
        if not output.strip().startswith(prefix):
            raise ConnectionAttributionError(
                "The audited Wi-Fi connection identity is unavailable"
            )
        network_name = output.strip()[len(prefix) :].strip()
        route_output = self._runner(["/usr/sbin/netstat", "-rn", "-f", "inet"])
        default_rows = [
            row.split()
            for row in route_output.splitlines()
            if row.split()
            and row.split()[0] == "default"
            and row.split()[-1] == self.interface_name
        ]
        if not network_name or len(default_rows) != 1 or len(default_rows[0]) < 2:
            raise ConnectionAttributionError(
                "The audited network connection cannot be identified safely"
            )
        identity = f"wifi-v1\0{network_name}\0{default_rows[0][1]}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()
