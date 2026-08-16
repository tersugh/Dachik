"""Provider-neutral traffic observation types."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TrafficDomain(StrEnum):
    """Accounting boundary represented by a traffic observation."""

    INTERFACE = "measured.interface"
    GATEWAY_WAN = "measured.gateway_wan"


@dataclass(frozen=True, slots=True)
class RawTrafficObservation:
    """A cumulative counter observation emitted by a traffic provider.

    Values are raw counter readings, not calculated usage for an interval.
    """

    provider_id: str
    series_id: str
    domain: TrafficDomain
    observed_at: datetime
    monotonic_ns: int
    session_id: str
    rx_bytes: int
    tx_bytes: int

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")
        if not self.series_id.strip():
            raise ValueError("series_id must not be empty")
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.monotonic_ns < 0:
            raise ValueError("monotonic_ns must be non-negative")
        if self.rx_bytes < 0 or self.tx_bytes < 0:
            raise ValueError("byte counters must be non-negative")
