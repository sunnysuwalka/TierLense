"""Investigation job API schemas, including execution progress and retry state."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

JobType = Literal["initial_scan", "manual_scan", "scheduled_scan"]
JobStatus = Literal["queued", "running", "completed", "failed"]


class InvestigationJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["manual_scan", "scheduled_scan"] = "manual_scan"
    scheduled_at: datetime | None = None

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone_if_provided(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone, e.g. Z or +00:00")
        return value


class InvestigationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    job_type: JobType
    status: JobStatus
    scheduled_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    error_summary: str | None
    next_attempt_at: datetime | None = None
    progress_percent: int = 0
    progress_message: str | None = None
    result_summary: dict[str, Any] | None = None
    execution_metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class InvestigationJobList(BaseModel):
    items: list[InvestigationJobRead]
    total: int
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
