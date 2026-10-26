"""Typed contracts shared by discovery, fetching, and LLM analysis providers."""

from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

SourceType = Literal[
    "official",
    "news",
    "documentation",
    "regulatory",
    "financial",
    "research",
    "other",
]
FindingType = Literal[
    "disruption_event",
    "supplier_relationship",
    "ownership_relationship",
    "policy_change",
    "financial_signal",
    "technical_dependency",
    "company_update",
    "other",
]
EventStatus = Literal["observed", "reported", "forecast", "risk_signal", "unclear"]
EntityType = Literal["organization", "facility", "component", "service", "country", "person", "other"]
RelationshipType = Literal[
    "supplies", "provides_component", "provides_service", "owns", "operates",
    "located_in", "manufactures_for", "distributes_to", "depends_on",
    "board_relationship", "country_dependency", "other_dependency",
]
DisruptionType = Literal[
    "operational_outage", "production_shutdown", "capacity_shortage", "cyber_incident",
    "natural_disaster", "labor_dispute", "logistics_disruption", "regulatory_action",
    "financial_distress", "supplier_loss", "geopolitical_event", "other",
]


class OrganizationContext(BaseModel):
    """Minimal organization/watch-profile context passed to providers."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    website: str | None = None
    country_code: str | None = None
    description: str | None = None
    dependency_role: str = "supplier"
    products_services: list[str] = Field(default_factory=list)
    dependency_context: str | None = None
    criticality: str = "medium"
    identity_clues: list[str] = Field(default_factory=list)


class SourceCandidate(BaseModel):
    """Untrusted search result; it is not itself a verified fact."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    url: AnyHttpUrl
    title: str = Field(default="Untitled source", min_length=1, max_length=1000)
    snippet: str = Field(default="", max_length=8000)
    source_type: SourceType = "other"
    published_at: datetime | None = None
    search_query: str = Field(default="", max_length=1000)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        return value.strip() or "Untitled source"


class FetchedDocument(BaseModel):
    """Processed, bounded document text plus acquisition metadata."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str | None = None
    content_type: str
    content_text: str
    content_hash: str
    fetched_at: datetime
    published_at: datetime | None = None
    http_status: int = 200
    is_truncated: bool = False
    metadata: dict = Field(default_factory=dict)


class RelevanceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevant: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=4000)
    categories: list[str] = Field(default_factory=list, max_length=20)


class ExtractedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_type: FindingType
    subject_name: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=255)
    object_value: str | None = Field(default=None, max_length=4000)
    summary: str = Field(min_length=1, max_length=8000)
    event_status: EventStatus = "unclear"
    event_date: str | None = Field(default=None, max_length=40)
    source_passage: str | None = Field(default=None, max_length=5000)
    confidence: float = Field(ge=0.0, le=1.0)
    # Optional structured fields used to construct graph edges/events. They are not
    # inferred from vague prose; the extraction prompt requires explicit source support.
    related_entity_name: str | None = Field(default=None, max_length=500)
    related_entity_type: EntityType | None = None
    relationship_type: RelationshipType | None = None
    component_or_service: str | None = Field(default=None, max_length=500)
    ownership_percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    is_state_owned: bool | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    disruption_type: DisruptionType | None = None
    severity: int | None = Field(default=None, ge=1, le=5)

    @field_validator("country_code")
    @classmethod
    def normalize_finding_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ExtractedFinding] = Field(default_factory=list, max_length=30)


class BatchRelevanceItem(BaseModel):
    """One locally validated relevance result keyed to a discovered source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=100)
    relevant: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=1000)
    categories: list[str] = Field(default_factory=list, max_length=20)


class BatchRelevanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessments: list[BatchRelevanceItem] = Field(min_length=1, max_length=50)


class BatchDocumentFindings(BaseModel):
    """Extracted findings attached to one exact source/document identifier."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=100)
    findings: list[ExtractedFinding] = Field(default_factory=list, max_length=30)


class BatchExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[BatchDocumentFindings] = Field(min_length=1, max_length=20)
