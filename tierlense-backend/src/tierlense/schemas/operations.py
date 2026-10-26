"""Sprint 4 schedule, history, source-change and alternative-supplier contracts."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvestigationSchedulePut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_minutes: int = Field(default=1440, ge=15, le=10080)


class InvestigationScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    enabled: bool
    interval_minutes: int
    next_run_at: datetime
    last_enqueued_at: datetime | None
    last_success_at: datetime | None
    last_job_id: UUID | None
    created_at: datetime
    updated_at: datetime


class EvidenceChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    job_id: UUID
    source_id: UUID
    previous_document_id: UUID | None
    current_document_id: UUID
    previous_content_hash: str | None
    current_content_hash: str
    change_type: str
    reassessment_status: str
    reassessment_details: dict[str, Any]
    detected_at: datetime


class InvestigationSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    job_id: UUID
    snapshot_at: datetime
    job_type: str
    result_summary: dict[str, Any]
    evidence_document_ids: list[UUID]
    finding_ids: list[UUID]
    graph_entity_ids: list[UUID]
    graph_relationship_ids: list[UUID]
    disruption_event_ids: list[UUID]
    risk_assessment_ids: list[UUID]
    graph_snapshot: dict[str, Any]
    evidence_change_ids: list[UUID]


class InvestigationSnapshotList(BaseModel):
    items: list[InvestigationSnapshotRead]
    total: int
    limit: int
    offset: int


class AlternativeSupplierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    required_function: str = Field(min_length=2, max_length=500)
    required_role: str | None = Field(default=None, max_length=100)
    required_country_codes: list[str] = Field(default_factory=list, max_length=50)
    excluded_country_codes: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("required_country_codes", "excluded_country_codes")
    @classmethod
    def normalize_country_codes(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            code = value.strip().upper()
            if len(code) != 2:
                raise ValueError("Country constraints must use two-letter country codes")
            if code not in cleaned:
                cleaned.append(code)
        return cleaned


class AlternativeSupplierCandidate(BaseModel):
    entity_id: UUID
    entity_name: str
    entity_type: str
    identity_status: str
    country_code: str | None
    match_index: float
    match_status: Literal["potential_match", "conditional_match"]
    matched_function: str | None
    relationship_id: UUID
    evidence_document_id: UUID
    evidence_url: str
    source_passage: str
    rationale: list[str]
    missing_information: list[str]


class AlternativeSupplierResult(BaseModel):
    id: UUID
    organization_id: UUID
    affected_entity_id: UUID
    required_function: str
    required_role: str | None
    constraints: dict[str, Any]
    result_status: Literal["potential_matches_found", "conditional_matches_only", "insufficient_evidence"]
    candidates: list[AlternativeSupplierCandidate]
    scoring_version: str
    created_at: datetime


class AlternativeSupplierHistory(BaseModel):
    items: list[AlternativeSupplierResult]
    total: int
    limit: int
    offset: int
