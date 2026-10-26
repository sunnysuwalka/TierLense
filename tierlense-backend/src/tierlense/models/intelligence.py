"""Persistent source discovery, document snapshots, and evidence-backed findings."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tierlense.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DiscoveredSource(Base):
    """A canonical public URL seen during one or more investigations."""

    __tablename__ = "discovered_sources"
    __table_args__ = (Index("ix_discovered_sources_domain", "source_domain"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    # Current content pointer is separate from historical EvidenceDocument versions.
    latest_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_document_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    last_content_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    documents: Mapped[list["EvidenceDocument"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    investigation_links: Mapped[list["InvestigationSource"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class EvidenceDocument(Base):
    """A content version for a URL; unchanged URL/content pairs are stored once."""

    __tablename__ = "evidence_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_evidence_source_content_hash"),
        Index("ix_evidence_documents_fetched_at", "fetched_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("discovered_sources.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    is_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    source: Mapped[DiscoveredSource] = relationship(back_populates="documents")
    investigation_links: Mapped[list["InvestigationSource"]] = relationship(
        back_populates="document"
    )
    findings: Mapped[list["InvestigationFinding"]] = relationship(back_populates="document")


class InvestigationSource(Base):
    """Association between a source and the investigation that discovered it."""

    __tablename__ = "investigation_sources"
    __table_args__ = (
        UniqueConstraint("job_id", "source_id", name="uq_investigation_source_job_source"),
        Index("ix_investigation_sources_job_relevant", "job_id", "relevant"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("discovered_sources.id", ondelete="CASCADE"), nullable=False
    )
    evidence_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_documents.id", ondelete="SET NULL"), nullable=True
    )
    search_query: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    discovery_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    job: Mapped["InvestigationJob"] = relationship(back_populates="discovered_sources")
    source: Mapped[DiscoveredSource] = relationship(back_populates="investigation_links")
    document: Mapped[EvidenceDocument | None] = relationship(back_populates="investigation_links")
    findings: Mapped[list["InvestigationFinding"]] = relationship(
        back_populates="investigation_source", cascade="all, delete-orphan"
    )


class InvestigationFinding(Base):
    """Structured claim extracted from a document with a traceable evidence passage."""

    __tablename__ = "investigation_findings"
    __table_args__ = (
        UniqueConstraint("job_id", "fingerprint", name="uq_investigation_finding_job_fingerprint"),
        Index("ix_investigation_findings_job_type", "job_id", "finding_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    investigation_source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_sources.id", ondelete="CASCADE"), nullable=False
    )
    evidence_document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(500), nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    object_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    event_status: Mapped[str] = mapped_column(String(48), nullable=False)
    event_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_passage: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    structured_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    job: Mapped["InvestigationJob"] = relationship(back_populates="findings")
    investigation_source: Mapped[InvestigationSource] = relationship(back_populates="findings")
    document: Mapped[EvidenceDocument] = relationship(back_populates="findings")
