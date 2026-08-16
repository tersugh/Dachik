"""Core traffic-provider contracts for Dachik collectors."""

from collector.models import RawTrafficObservation, TrafficDomain
from collector.providers import TrafficProvider

__all__ = ["RawTrafficObservation", "TrafficDomain", "TrafficProvider"]
