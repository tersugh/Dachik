"""Traffic provider boundary shared by local and future gateway collectors."""

from typing import Protocol, runtime_checkable

from collector.models import RawTrafficObservation


@runtime_checkable
class TrafficProvider(Protocol):
    """Source of provider-neutral cumulative traffic observations."""

    @property
    def provider_id(self) -> str:
        """Return the stable identifier for this provider instance."""
        ...

    async def observe(self) -> tuple[RawTrafficObservation, ...]:
        """Read the provider's current cumulative counters."""
        ...
