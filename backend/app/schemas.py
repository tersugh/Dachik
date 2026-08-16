"""Public API response schemas."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["dachik"] = "dachik"
    version: str


class ErrorResponse(BaseModel):
    error: str
    detail: str
