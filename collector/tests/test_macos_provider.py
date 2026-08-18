import asyncio
from collections.abc import Sequence

import pytest

from collector.macos import (
    CommandRunner,
    ConnectionAttributionError,
    InterfaceAmbiguityError,
    MacOSTrafficProvider,
)


def runner_for(counters: tuple[int, int] = (1_000, 500)) -> CommandRunner:
    def run(command: Sequence[str]) -> str:
        if command[:3] == ["/usr/sbin/netstat", "-rn", "-f"]:
            return "Destination Gateway Flags Netif Expire\ndefault 192.0.2.1 UGScg en0\n"
        if command[:2] == ["/sbin/ifconfig", "en0"]:
            return "en0: flags=8863<UP,RUNNING> mtu 1500\n\tstatus: active\n"
        if command[:2] == ["/usr/sbin/sysctl", "-n"]:
            return "synthetic-boot-id\n"
        if command[:2] == ["/usr/sbin/networksetup", "-getairportnetwork"]:
            return "Current Wi-Fi Network: Synthetic Audit Network\n"
        if command[:2] == ["/usr/sbin/netstat", "-bI"]:
            return (
                "Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
                f"en0 1500 <Link#4> aa:bb 10 0 {counters[0]} 8 0 {counters[1]} 0\n"
            )
        raise AssertionError(f"Unexpected command: {command}")

    return run


def test_macos_provider_selects_default_physical_interface_and_reads_bytes() -> None:
    provider = MacOSTrafficProvider(runner=runner_for(), run_id="synthetic-run")
    observation = asyncio.run(provider.observe())[0]

    assert provider.interface_name == "en0"
    assert len(provider.connection_fingerprint) == 64
    assert observation.rx_bytes == 1_000
    assert observation.tx_bytes == 500
    assert observation.session_id == "synthetic-boot-id/synthetic-run"


def test_macos_provider_rejects_ambiguous_default_interfaces() -> None:
    def ambiguous_runner(command: Sequence[str]) -> str:
        if command[:3] == ["/usr/sbin/netstat", "-rn", "-f"]:
            return (
                "Destination Gateway Flags Netif Expire\n"
                "default 192.0.2.1 UGScg en0\n"
                "default 192.0.2.2 UGScg en1\n"
            )
        raise AssertionError(f"Unexpected command: {command}")

    with pytest.raises(InterfaceAmbiguityError):
        MacOSTrafficProvider(runner=ambiguous_runner)


def test_same_interface_network_change_stops_attribution() -> None:
    network = ["Audited Network"]
    base_runner = runner_for()

    def changing_runner(command: Sequence[str]) -> str:
        if command[:2] == ["/usr/sbin/networksetup", "-getairportnetwork"]:
            return f"Current Wi-Fi Network: {network[0]}\n"
        return base_runner(command)

    provider = MacOSTrafficProvider(runner=changing_runner)
    network[0] = "Different Network"

    with pytest.raises(ConnectionAttributionError):
        asyncio.run(provider.observe())

    network[0] = "Audited Network"
    resumed = MacOSTrafficProvider(runner=changing_runner, run_id="resumed-run")
    observation = asyncio.run(resumed.observe())[0]

    assert resumed.connection_fingerprint == provider.connection_fingerprint
    assert observation.session_id.endswith("/resumed-run")
