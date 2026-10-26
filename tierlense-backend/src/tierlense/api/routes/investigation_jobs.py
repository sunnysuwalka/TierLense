"""Global investigation job query endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from tierlense.db.session import get_db
from tierlense.schemas.investigation_job import (
    InvestigationJobList,
    InvestigationJobRead,
    JobStatus,
)
from tierlense.services import investigation_jobs

router = APIRouter(prefix="/investigation-jobs", tags=["investigation jobs"])


@router.get("", response_model=InvestigationJobList, summary="List and filter investigation jobs")
def get_investigation_jobs(
    organization_id: UUID | None = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> InvestigationJobList:
    items, total = investigation_jobs.list_jobs(
        db,
        organization_id=organization_id,
        status=job_status,
        limit=limit,
        offset=offset,
    )
    return InvestigationJobList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=InvestigationJobRead, summary="Get an investigation job")
def get_investigation_job(job_id: UUID, db: Session = Depends(get_db)) -> InvestigationJobRead:
    job = investigation_jobs.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Investigation job not found")
    return InvestigationJobRead.model_validate(job)
