"""Read APIs for evidence sources, extracted findings, and pipeline progress."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from tierlense.db.session import get_db
from tierlense.models import InvestigationFinding, InvestigationJob, InvestigationSource
from tierlense.schemas.intelligence import (
    EvidencePipelineStatus,
    InvestigationFindingList,
    InvestigationFindingRead,
    InvestigationSourceList,
    InvestigationSourceRead,
)

router = APIRouter(prefix="/investigation-jobs", tags=["investigation results"])


@router.get("/{job_id}/sources", response_model=InvestigationSourceList, summary="List discovered sources for an investigation")
def list_investigation_sources(
    job_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> InvestigationSourceList:
    if db.get(InvestigationJob, job_id) is None:
        raise HTTPException(status_code=404, detail="Investigation job not found")
    base = select(InvestigationSource).options(
        joinedload(InvestigationSource.source), joinedload(InvestigationSource.document)
    ).where(InvestigationSource.job_id == job_id)
    rows = list(db.scalars(base.order_by(InvestigationSource.discovered_at.asc()).limit(limit).offset(offset)).all())
    total = int(db.scalar(select(func.count(InvestigationSource.id)).where(InvestigationSource.job_id == job_id)) or 0)
    items = [
        InvestigationSourceRead(
            id=row.id,
            job_id=row.job_id,
            source_id=row.source_id,
            url=row.source.canonical_url,
            domain=row.source.source_domain,
            title=row.source.title,
            source_type=row.source.source_type,
            search_query=row.search_query,
            discovery_snippet=row.discovery_snippet,
            relevant=row.relevant,
            relevance_score=row.relevance_score,
            relevance_reason=row.relevance_reason,
            relevance_categories=row.relevance_categories or [],
            fetch_status=row.fetch_status,
            error_summary=row.error_summary,
            evidence_document_id=row.evidence_document_id,
            content_hash=row.document.content_hash if row.document else None,
            content_type=row.document.content_type if row.document else None,
            published_at=row.document.published_at if row.document else None,
            fetched_at=row.document.fetched_at if row.document else None,
            discovered_at=row.discovered_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return InvestigationSourceList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}/findings", response_model=InvestigationFindingList, summary="List evidence-backed findings for an investigation")
def list_investigation_findings(
    job_id: UUID,
    validation_status: str | None = Query(default=None, max_length=32),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> InvestigationFindingList:
    if db.get(InvestigationJob, job_id) is None:
        raise HTTPException(status_code=404, detail="Investigation job not found")
    predicates = [InvestigationFinding.job_id == job_id]
    if validation_status:
        predicates.append(InvestigationFinding.validation_status == validation_status)
    statement = select(InvestigationFinding).where(*predicates)
    rows = list(db.scalars(statement.order_by(InvestigationFinding.created_at.asc()).limit(limit).offset(offset)).all())
    total = int(db.scalar(select(func.count(InvestigationFinding.id)).where(*predicates)) or 0)
    return InvestigationFindingList(
        items=[InvestigationFindingRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}/pipeline-status", response_model=EvidencePipelineStatus, summary="Get investigation progress and result counters")
def get_pipeline_status(job_id: UUID, db: Session = Depends(get_db)) -> EvidencePipelineStatus:
    job = db.get(InvestigationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Investigation job not found")
    return EvidencePipelineStatus(
        job_id=job.id,
        status=job.status,
        progress_percent=job.progress_percent,
        progress_message=job.progress_message,
        result_summary=job.result_summary,
        error_summary=job.error_summary,
    )
