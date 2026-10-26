"""API contracts for the supply-chain graph and disruption intelligence."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
EventStatus = Literal["observed", "reported", "forecast", "risk_signal", "unclear"]


class SupplyChainEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=500)
    entity_type: EntityType = "organization"
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Entity name cannot be blank")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in values if item and item.strip()))

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class SupplyChainEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    normalized_name: str
    entity_type: EntityType
    country_code: str | None
    aliases: list[str]
    identity_status: str
    resolution_confidence: float
    is_root: bool
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SupplyChainEntityCreateResult(BaseModel):
    entity: SupplyChainEntityRead
    resolution_action: Literal["matched_exact", "created_needs_review", "created_root"]
    note: str


class SupplyChainEntityList(BaseModel):
    items: list[SupplyChainEntityRead]
    total: int


class SupplyChainRelationshipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: RelationshipType
    evidence_document_id: UUID
    source_finding_id: UUID | None = None
    source_passage: str = Field(min_length=12, max_length=5000)
    component_or_service: str | None = Field(default=None, max_length=500)
    ownership_percentage: float | None = Field(default=None, ge=0.0, le=100.0)
    is_state_owned: bool | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    as_of_date: str | None = Field(default=None, max_length=40)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class SupplyChainRelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    source_entity_id: UUID
    source_entity_name: str
    target_entity_id: UUID
    target_entity_name: str
    relationship_type: RelationshipType
    component_or_service: str | None
    ownership_percentage: float | None
    is_state_owned: bool | None
    country_code: str | None
    as_of_date: str | None
    confidence: float
    validation_status: str
    evidence_document_id: UUID
    evidence_url: str
    source_finding_id: UUID | None
    source_passage: str
    attributes: dict[str, Any]
    created_at: datetime


class SupplyChainRelationshipList(BaseModel):
    items: list[SupplyChainRelationshipRead]
    total: int


class SupplyChainRelationshipCreateResult(BaseModel):
    relationship: SupplyChainRelationshipRead
    created: bool
    note: str


class DisruptionEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    affected_entity_id: UUID
    event_type: DisruptionType
    event_status: EventStatus = "reported"
    severity: int | None = Field(default=None, ge=1, le=5)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    event_date: str | None = Field(default=None, max_length=40)
    summary: str = Field(min_length=1, max_length=5000)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_document_id: UUID
    source_finding_id: UUID | None = None
    source_passage: str = Field(min_length=12, max_length=5000)

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class DisruptionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    affected_entity_id: UUID
    affected_entity_name: str
    event_type: DisruptionType
    event_status: EventStatus
    severity: int | None
    country_code: str | None
    event_date: str | None
    summary: str
    confidence: float
    validation_status: str
    evidence_document_id: UUID
    evidence_url: str
    source_finding_id: UUID | None
    source_passage: str
    is_prediction: bool
    created_at: datetime
    updated_at: datetime


class DisruptionEventList(BaseModel):
    items: list[DisruptionEventRead]
    total: int


class DisruptionEventCreateResult(BaseModel):
    event: DisruptionEventRead
    created: bool
    note: str


class GraphRelationship(BaseModel):
    id: UUID
    source_entity_id: UUID
    source_entity_name: str
    target_entity_id: UUID
    target_entity_name: str
    relationship_type: RelationshipType
    component_or_service: str | None
    ownership_percentage: float | None
    country_code: str | None
    validation_status: str
    evidence_document_id: UUID
    source_passage: str


class GraphNode(BaseModel):
    entity: SupplyChainEntityRead
    depth: int = Field(ge=0)
    path_entity_ids: list[UUID] = Field(default_factory=list)


class SupplyChainGraphRead(BaseModel):
    organization_id: UUID
    root_entity_id: UUID
    direction: Literal["upstream", "downstream", "both"]
    max_depth: int
    tier_definition: str
    nodes: list[GraphNode]
    relationships: list[GraphRelationship]


class ImpactedEntity(BaseModel):
    entity: SupplyChainEntityRead
    depth: int
    path_entity_ids: list[UUID]
    path_relationship_ids: list[UUID]
    exposure_reason: str


class DownstreamImpactRead(BaseModel):
    organization_id: UUID
    origin_entity_id: UUID
    origin_entity_name: str
    event_id: UUID | None = None
    max_depth: int
    affected_entities: list[ImpactedEntity]
    notes: list[str]


class DisruptionLikelihoodRead(BaseModel):
    id: UUID
    organization_id: UUID
    entity_id: UUID
    entity_name: str
    experimental_index: float
    score_is_probability: Literal[False] = False
    band: str
    rationale: list[str]
    inputs: dict[str, Any]
    model_version: str
    is_experimental: Literal[True] = True
    is_calibrated: Literal[False] = False
    assessed_at: datetime
    caveat: str = "Experimental rule-based index; not a calibrated probability or validated prediction."


class EvidencePassageRead(BaseModel):
    record_type: Literal["finding", "relationship", "disruption_event"]
    record_id: UUID
    validation_status: str
    passage: str


class EvidenceInspectionRead(BaseModel):
    organization_id: UUID
    document_id: UUID
    source_url: str
    title: str | None
    content_hash: str
    content_type: str
    published_at: datetime | None
    fetched_at: datetime
    is_truncated: bool
    content_excerpt: str
    passages: list[EvidencePassageRead]
