"""Evidence-backed supply-chain graph, disruption events and experimental assessments."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from tierlense.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SupplyChainEntity(Base):
    """An entity node scoped to one monitored organization's supply-chain graph."""

    __tablename__ = "supply_chain_entities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "normalized_name", "entity_type",
            name="uq_supply_entity_name_type",
        ),
        Index("ix_supply_entities_org_type", "organization_id", "entity_type"),
        Index("ix_supply_entities_org_country", "organization_id", "country_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="organization")
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    identity_status: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    resolution_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class SupplyChainRelationship(Base):
    """A directed, evidence-backed edge. Dependency edges are normalized upstream -> downstream."""

    __tablename__ = "supply_chain_relationships"
    __table_args__ = (
        UniqueConstraint("organization_id", "fingerprint", name="uq_supply_relationship_fingerprint"),
        Index("ix_supply_relationships_org_source", "organization_id", "source_entity_id"),
        Index("ix_supply_relationships_org_target", "organization_id", "target_entity_id"),
        Index("ix_supply_relationships_type", "organization_id", "relationship_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    source_entity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supply_chain_entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supply_chain_entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(48), nullable=False)
    component_or_service: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ownership_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_state_owned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    as_of_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="passage_verified")
    evidence_document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False
    )
    source_finding_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_findings.id", ondelete="SET NULL"), nullable=True
    )
    source_passage: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DisruptionEvent(Base):
    """A source-linked reported event or signal; predictions live in a separate assessment table."""

    __tablename__ = "disruption_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "fingerprint", name="uq_disruption_event_fingerprint"),
        Index("ix_disruption_events_org_entity", "organization_id", "affected_entity_id"),
        Index("ix_disruption_events_org_status", "organization_id", "event_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    affected_entity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supply_chain_entities.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    event_status: Mapped[str] = mapped_column(String(32), nullable=False, default="reported")
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    event_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="passage_verified")
    evidence_document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False
    )
    source_finding_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_findings.id", ondelete="SET NULL"), nullable=True
    )
    source_passage: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    is_prediction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DisruptionLikelihoodAssessment(Base):
    """Transparent experimental index; score is explicitly not a calibrated probability."""

    __tablename__ = "disruption_likelihood_assessments"
    __table_args__ = (
        Index("ix_disruption_assessment_org_entity_time", "organization_id", "entity_id", "assessed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supply_chain_entities.id", ondelete="CASCADE"), nullable=False
    )
    experimental_index: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="experimental-rules-v1")
    is_experimental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_calibrated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
