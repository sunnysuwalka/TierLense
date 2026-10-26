"""Read-only response schemas for discovered sources and extracted evidence."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InvestigationSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    source_id: UUID
    url: str
    domain: str
    title: str | None
    source_type: str
    search_query: str | None
    discovery_snippet: str | None
    relevant: bool | None
    relevance_score: float | None
    relevance_reason: str | None
    relevance_categories: list[str]
    fetch_status: str
    error_summary: str | None
    evidence_document_id: UUID | None
    content_hash: str | None = None
    content_type: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    discovered_at: datetime
    updated_at: datetime


class InvestigationFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    organization_id: UUID
    investigation_source_id: UUID
    evidence_document_id: UUID
    finding_type: str
    subject_name: str
    predicate: str
    object_value: str | None
    summary: str
    event_status: str
    event_date: str | None
    source_passage: str | None
    model_confidence: float
    validation_status: str
    structured_details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class InvestigationSourceList(BaseModel):
    items: list[InvestigationSourceRead]
    total: int
    limit: int
    offset: int


class InvestigationFindingList(BaseModel):
    items: list[InvestigationFindingRead]
    total: int
    limit: int
    offset: int


class EvidencePipelineStatus(BaseModel):
    """Compact job/result status for clients that don't need the full job payload."""

    job_id: UUID
    status: str
    progress_percent: int
    progress_message: str | None
    result_summary: dict[str, Any] | None
    error_summary: str | None
    execution_metrics: dict[str, Any] = Field(default_factory=dict)
