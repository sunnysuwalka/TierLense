"""Sprint 4 autonomous scheduling, historical snapshots, source changes and alternatives."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from tierlense.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvestigationSchedule(Base):
    """Per-organization recurring scan schedule, serviced by the existing worker."""

    __tablename__ = "investigation_schedules"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_investigation_schedule_organization"),
        Index("ix_investigation_schedules_due", "enabled", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class EvidenceChange(Base):
    """A detected source-content version change and its risk reassessment trail."""

    __tablename__ = "evidence_changes"
    __table_args__ = (
        Index("ix_evidence_changes_org_detected", "organization_id", "detected_at"),
        Index("ix_evidence_changes_job_status", "job_id", "reassessment_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("investigation_jobs.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("discovered_sources.id", ondelete="CASCADE"), nullable=False)
    previous_document_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence_documents.id", ondelete="SET NULL"), nullable=True)
    current_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False)
    previous_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False, default="content_changed")
    reassessment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reassessment_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class InvestigationSnapshot(Base):
    """Immutable, timestamped pointer snapshot for one completed investigation job."""

    __tablename__ = "investigation_snapshots"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_investigation_snapshot_job"),
        Index("ix_investigation_snapshots_org_time", "organization_id", "snapshot_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("investigation_jobs.id", ondelete="CASCADE"), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_document_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    finding_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    graph_entity_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    graph_relationship_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    disruption_event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risk_assessment_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    graph_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_change_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class SupplierRecommendation(Base):
    """Persisted, explainable alternative-candidate assessment based only on graph evidence."""

    __tablename__ = "supplier_recommendations"
    __table_args__ = (
        Index("ix_supplier_recommendations_org_time", "organization_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    affected_entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supply_chain_entities.id", ondelete="CASCADE"), nullable=False)
    source_job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("investigation_jobs.id", ondelete="SET NULL"), nullable=True)
    required_function: Mapped[str] = mapped_column(String(500), nullable=False)
    required_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False, default="insufficient_evidence")
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False, default="deterministic-function-match-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
