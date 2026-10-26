"""Organization registry and onboarding endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from tierlense.db.session import get_db
from tierlense.schemas.investigation_job import (
    InvestigationJobCreate,
    InvestigationJobList,
    InvestigationJobRead,
)
from tierlense.schemas.onboarding import OrganizationOnboardedResponse
from tierlense.schemas.organization import (
    OrganizationCreate,
    OrganizationList,
    OrganizationRead,
    OrganizationUpdate,
    WatchProfileInput,
    WatchProfileRead,
)
from tierlense.services import investigation_jobs, organizations

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOnboardedResponse, status_code=status.HTTP_201_CREATED, summary="Register an organization")
def onboard_organization(
    payload: OrganizationCreate, db: Session = Depends(get_db)
) -> OrganizationOnboardedResponse:
    organization, job = organizations.onboard_organization(db, payload)
    summary = getattr(job, "result_summary", None) or {}
    if summary.get("demo_scenario_id") == "pds4_army_logistics_v1":
        notice = (
            "SIMULATED PDS-4 demo data loaded locally. All supplier names, ownership records, "
            "relationships, disruption scenarios and evidence are fictional. No external sources "
            "or model providers were called. Risk indexes are experimental and uncalibrated."
        )
    else:
        notice = (
            "Organization registered. Its initial investigation is queued and will run when the "
            "background worker claims it; supplier identity and findings remain subject to validation."
        )
    return OrganizationOnboardedResponse(
        organization=OrganizationRead.model_validate(organization),
        initial_investigation=InvestigationJobRead.model_validate(job),
        notice=notice,
    )


@router.get("", response_model=OrganizationList, summary="List and search organizations")
def get_organizations(
    q: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> OrganizationList:
    items, total = organizations.list_organizations(db, query=q, limit=limit, offset=offset)
    return OrganizationList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{organization_id}", response_model=OrganizationRead, summary="Get an organization")
def get_organization(
    organization_id: UUID, db: Session = Depends(get_db)
) -> OrganizationRead:
    organization = organizations.get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationRead.model_validate(organization)


@router.patch("/{organization_id}", response_model=OrganizationRead, summary="Update organization identity fields")
def patch_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
) -> OrganizationRead:
    organization = organizations.get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        updated = organizations.update_organization(db, organization, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OrganizationRead.model_validate(updated)


@router.put("/{organization_id}/watch-profile", response_model=WatchProfileRead, summary="Create or replace a watch profile")
def put_watch_profile(
    organization_id: UUID,
    payload: WatchProfileInput,
    db: Session = Depends(get_db),
) -> WatchProfileRead:
    organization = organizations.get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    profile = organizations.replace_watch_profile(db, organization, payload)
    return WatchProfileRead.model_validate(profile)


@router.get(
    "/{organization_id}/investigation-jobs",
    response_model=InvestigationJobList,
    summary="List investigations for an organization",
)
def get_organization_jobs(
    organization_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> InvestigationJobList:
    organization = organizations.get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    items, total = investigation_jobs.list_jobs_for_organization(
        db, organization_id, limit=limit, offset=offset
    )
    return InvestigationJobList(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/{organization_id}/investigation-jobs",
    response_model=InvestigationJobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Queue an investigation record",
)
def queue_investigation(
    organization_id: UUID,
    payload: InvestigationJobCreate,
    db: Session = Depends(get_db),
) -> InvestigationJobRead:
    organization = organizations.get_organization(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    job = investigation_jobs.create_job(db, organization, payload)
    return InvestigationJobRead.model_validate(job)
