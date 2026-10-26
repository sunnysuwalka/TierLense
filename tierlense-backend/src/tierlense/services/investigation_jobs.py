"""Durable investigation scheduling records (not job execution)."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tierlense.models import InvestigationJob, Organization
from tierlense.schemas.investigation_job import InvestigationJobCreate


def create_job(
    db: Session, organization: Organization, payload: InvestigationJobCreate
) -> InvestigationJob:
    job = InvestigationJob(
        organization_id=organization.id,
        job_type=payload.job_type,
        status="queued",
        scheduled_at=payload.scheduled_at or datetime.now(timezone.utc),
        attempt_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs(
    db: Session,
    *,
    organization_id: UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[InvestigationJob], int]:
    statement = select(InvestigationJob)
    count_statement = select(func.count(InvestigationJob.id))
    if organization_id:
        statement = statement.where(InvestigationJob.organization_id == organization_id)
        count_statement = count_statement.where(InvestigationJob.organization_id == organization_id)
    if status:
        statement = statement.where(InvestigationJob.status == status)
        count_statement = count_statement.where(InvestigationJob.status == status)
    items = list(
        db.scalars(statement.order_by(InvestigationJob.created_at.desc()).limit(limit).offset(offset)).all()
    )
    total = int(db.scalar(count_statement) or 0)
    return items, total


def get_job(db: Session, job_id: UUID) -> InvestigationJob | None:
    return db.get(InvestigationJob, job_id)


def list_jobs_for_organization(
    db: Session, organization_id: UUID, *, limit: int, offset: int
) -> tuple[list[InvestigationJob], int]:
    return list_jobs(
        db,
        organization_id=organization_id,
        status=None,
        limit=limit,
        offset=offset,
    )
