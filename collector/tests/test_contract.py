import asyncio
from datetime import UTC, datetime

import pytest

from collector import RawTrafficObservation, TrafficDomain, TrafficProvider


class StubTrafficProvider:
    provider_id = "stub"

    async def observe(self) -> tuple[RawTrafficObservation, ...]:
        return (
            RawTrafficObservation(
                provider_id=self.provider_id,
                series_id="en0",
                domain=TrafficDomain.INTERFACE,
                observed_at=datetime.now(UTC),
                monotonic_ns=1,
                session_id="test-session",
                rx_bytes=10,
                tx_bytes=20,
            ),
        )


def test_provider_satisfies_runtime_contract() -> None:
    provider = StubTrafficProvider()

    assert isinstance(provider, TrafficProvider)
    observations = asyncio.run(provider.observe())
    assert observations[0].provider_id == provider.provider_id
    assert observations[0].domain is TrafficDomain.INTERFACE


def test_observation_rejects_negative_counters() -> None:
    with pytest.raises(ValueError, match="byte counters"):
        RawTrafficObservation(
            provider_id="stub",
            series_id="en0",
            domain=TrafficDomain.INTERFACE,
            observed_at=datetime.now(UTC),
            monotonic_ns=1,
            session_id="test-session",
            rx_bytes=-1,
            tx_bytes=0,
        )
