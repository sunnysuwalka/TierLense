"""Durable queue records and observable investigation execution state."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tierlense.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvestigationJob(Base):
    __tablename__ = "investigation_jobs"
    __table_args__ = (
        Index("ix_investigation_jobs_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_investigation_jobs_next_attempt_at", "next_attempt_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="initial_scan")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    organization: Mapped["Organization"] = relationship(back_populates="investigation_jobs")
    discovered_sources: Mapped[list["InvestigationSource"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    findings: Mapped[list["InvestigationFinding"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
