"""
FleetGuard Pulse - Common Schemas.
Pagination envelopes, health probe responses, and structured error models.
"""

from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationMeta(BaseModel):
    page: int = Field(..., ge=1, description="Current page number (1-indexed)")
    limit: int = Field(..., ge=1, le=200, description="Page size limit")
    total_count: int = Field(..., ge=0, description="Total matching records")
    total_pages: int = Field(..., ge=0, description="Total available pages")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    pagination: PaginationMeta


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["HEALTHY"])
    timestamp: str
    service: str = "fleetguard-pulse-api"
    version: str = "1.0.0"


class ReadinessDatastoreStatus(BaseModel):
    postgres: bool
    redis: bool
    clickhouse: bool


class ReadinessResponse(BaseModel):
    status: str = Field(..., examples=["READY"])
    datastores: ReadinessDatastoreStatus
    timestamp: str
