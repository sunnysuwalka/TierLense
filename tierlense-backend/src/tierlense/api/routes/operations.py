"""Sprint 4 autonomous operations, history, change and alternative-supplier APIs."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tierlense.db.session import get_db
from tierlense.models import (
    EvidenceChange,
    InvestigationSchedule,
    InvestigationSnapshot,
    Organization,
    SupplierRecommendation,
)
from tierlense.schemas.operations import (
    AlternativeSupplierHistory,
    AlternativeSupplierRequest,
    AlternativeSupplierResult,
    EvidenceChangeRead,
    InvestigationSchedulePut,
    InvestigationScheduleRead,
    InvestigationSnapshotList,
    InvestigationSnapshotRead,
)
from tierlense.services.operations import configure_schedule, ensure_schedule, list_evidence_changes, recommend_alternatives

router = APIRouter(prefix="/organizations", tags=["autonomous operations"])


def _organization(db: Session, organization_id: UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def _recommendation_read(row: SupplierRecommendation) -> AlternativeSupplierResult:
    # Pydantic validates and converts nested UUID strings from the JSON snapshot.
    return AlternativeSupplierResult(
        id=row.id,
        organization_id=row.organization_id,
        affected_entity_id=row.affected_entity_id,
        required_function=row.required_function,
        required_role=row.required_role,
        constraints=row.constraints or {},
        result_status=row.result_status,
        candidates=row.candidates or [],
        scoring_version=row.scoring_version,
        created_at=row.created_at,
    )


@router.get("/{organization_id}/scan-schedule", response_model=InvestigationScheduleRead,
            summary="Get recurring investigation schedule")
def get_scan_schedule(organization_id: UUID, db: Session = Depends(get_db)) -> InvestigationScheduleRead:
    organization = _organization(db, organization_id)
    schedule = ensure_schedule(db, organization)
    db.commit()
    db.refresh(schedule)
    return InvestigationScheduleRead.model_validate(schedule)


@router.put("/{organization_id}/scan-schedule", response_model=InvestigationScheduleRead,
            summary="Configure recurring scans")
def put_scan_schedule(
    organization_id: UUID, payload: InvestigationSchedulePut, db: Session = Depends(get_db)
) -> InvestigationScheduleRead:
    organization = _organization(db, organization_id)
    try:
        schedule = configure_schedule(
            db, organization, enabled=payload.enabled, interval_minutes=payload.interval_minutes
        )
        db.commit()
        db.refresh(schedule)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InvestigationScheduleRead.model_validate(schedule)


@router.get("/{organization_id}/history", response_model=InvestigationSnapshotList,
            summary="List timestamped completed-investigation snapshots")
def get_history(
    organization_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> InvestigationSnapshotList:
    _organization(db, organization_id)
    predicates = [InvestigationSnapshot.organization_id == organization_id]
    items = list(db.scalars(
        select(InvestigationSnapshot).where(*predicates)
        .order_by(InvestigationSnapshot.snapshot_at.desc()).limit(limit).offset(offset)
    ).all())
    total = int(db.scalar(select(func.count(InvestigationSnapshot.id)).where(*predicates)) or 0)
    return InvestigationSnapshotList(
        items=[InvestigationSnapshotRead.model_validate(item) for item in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{organization_id}/history/{snapshot_id}", response_model=InvestigationSnapshotRead,
            summary="Get one historical investigation snapshot")
def get_history_item(
    organization_id: UUID, snapshot_id: UUID, db: Session = Depends(get_db)
) -> InvestigationSnapshotRead:
    _organization(db, organization_id)
    item = db.scalar(select(InvestigationSnapshot).where(
        InvestigationSnapshot.organization_id == organization_id,
        InvestigationSnapshot.id == snapshot_id,
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Investigation snapshot not found")
    return InvestigationSnapshotRead.model_validate(item)


@router.get("/{organization_id}/evidence-changes", response_model=list[EvidenceChangeRead],
            summary="List detected source-content changes and reassessment outcomes")
def get_evidence_change_history(
    organization_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[EvidenceChangeRead]:
    _organization(db, organization_id)
    rows, _total = list_evidence_changes(db, organization_id, limit=limit, offset=offset)
    return [EvidenceChangeRead.model_validate(row) for row in rows]


@router.post("/{organization_id}/entities/{entity_id}/alternative-suppliers",
             response_model=AlternativeSupplierResult, status_code=status.HTTP_201_CREATED,
             summary="Persist an evidence-backed, deterministic alternative-supplier assessment")
def post_alternative_suppliers(
    organization_id: UUID,
    entity_id: UUID,
    payload: AlternativeSupplierRequest,
    db: Session = Depends(get_db),
) -> AlternativeSupplierResult:
    organization = _organization(db, organization_id)
    try:
        row = recommend_alternatives(db, organization, entity_id, payload)
        db.commit()
        db.refresh(row)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _recommendation_read(row)


@router.get("/{organization_id}/alternative-supplier-recommendations",
            response_model=AlternativeSupplierHistory,
            summary="List historical alternative-supplier assessments")
def get_alternative_supplier_history(
    organization_id: UUID,
    affected_entity_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> AlternativeSupplierHistory:
    _organization(db, organization_id)
    predicates = [SupplierRecommendation.organization_id == organization_id]
    if affected_entity_id:
        predicates.append(SupplierRecommendation.affected_entity_id == affected_entity_id)
    items = list(db.scalars(
        select(SupplierRecommendation).where(*predicates)
        .order_by(SupplierRecommendation.created_at.desc()).limit(limit).offset(offset)
    ).all())
    total = int(db.scalar(select(func.count(SupplierRecommendation.id)).where(*predicates)) or 0)
    return AlternativeSupplierHistory(
        items=[_recommendation_read(item) for item in items], total=total, limit=limit, offset=offset
    )
