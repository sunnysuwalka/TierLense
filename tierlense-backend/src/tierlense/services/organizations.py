"""Organization onboarding and registry operations."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from tierlense.core.config import get_settings
from tierlense.models import InvestigationJob, InvestigationSchedule, Organization, WatchProfile
from tierlense.schemas.organization import OrganizationCreate, OrganizationUpdate, WatchProfileInput


def _website_value(website: object) -> str | None:
    return str(website) if website is not None else None


def onboard_organization(db: Session, payload: OrganizationCreate) -> tuple[Organization, InvestigationJob]:
    """Create an organization, watch profile, recurring schedule and initial job atomically.

    When the local demo flag is enabled and the exact PDS-4 fixture name is used,
    seed a deterministic synthetic dataset in this same transaction. The job is
    committed as completed, so a running worker cannot claim it or call a model.
    Other organization registrations retain the normal queued initial scan flow.
    """
    # Lazy import prevents the scenario module from being loaded for normal signups.
    from tierlense.demo.pds4_army_logistics import (
        DEMO_ORGANIZATION_NAME,
        seed_pds4_army_logistics_demo,
    )

    settings = get_settings()
    is_pds4_demo = (
        settings.enable_pds4_demo_scenario
        and payload.name.strip().casefold() == DEMO_ORGANIZATION_NAME.casefold()
    )

    now = datetime.now(timezone.utc)
    organization = Organization(
        name=payload.name,
        website=_website_value(payload.website),
        country_code=payload.country_code,
        description=payload.description,
        identity_status="unverified",
    )
    profile_values = payload.watch_profile.model_dump()
    profile = WatchProfile(organization=organization, **profile_values)
    job = InvestigationJob(
        organization=organization,
        job_type="initial_scan",
        status="completed" if is_pds4_demo else "queued",
        scheduled_at=now,
        started_at=now if is_pds4_demo else None,
        finished_at=now if is_pds4_demo else None,
        attempt_count=0,
    )
    db.add_all([organization, profile, job])
    db.flush()  # Materialize IDs before schedule and evidence references are created.
    schedule = InvestigationSchedule(
        organization_id=organization.id,
        enabled=True,
        interval_minutes=1440,
        next_run_at=now + timedelta(minutes=1440),
    )
    db.add(schedule)

    try:
        if is_pds4_demo:
            seed_pds4_army_logistics_demo(db, organization, job)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(organization)
    db.refresh(profile)
    db.refresh(job)
    return organization, job


def list_organizations(
    db: Session, *, query: str | None, limit: int, offset: int
) -> tuple[list[Organization], int]:
    statement = select(Organization).options(selectinload(Organization.watch_profile))
    count_statement = select(func.count(Organization.id))
    if query:
        search = f"%{query.strip()}%"
        predicate = or_(Organization.name.ilike(search), Organization.description.ilike(search))
        statement = statement.where(predicate)
        count_statement = count_statement.where(predicate)
    items = list(
        db.scalars(statement.order_by(Organization.created_at.desc()).limit(limit).offset(offset)).all()
    )
    total = int(db.scalar(count_statement) or 0)
    return items, total


def get_organization(db: Session, organization_id: UUID) -> Organization | None:
    return db.scalar(
        select(Organization)
        .options(selectinload(Organization.watch_profile))
        .where(Organization.id == organization_id)
    )


def update_organization(
    db: Session, organization: Organization, payload: OrganizationUpdate
) -> Organization:
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise ValueError("Organization name cannot be null")
    if "website" in changes:
        changes["website"] = _website_value(changes["website"])
    for field, value in changes.items():
        setattr(organization, field, value)
    organization.updated_at = datetime.now(timezone.utc)
    db.add(organization)
    db.commit()
    return get_organization(db, organization.id) or organization


def replace_watch_profile(db: Session, organization: Organization, payload: WatchProfileInput) -> WatchProfile:
    profile = organization.watch_profile
    values = payload.model_dump()
    if profile is None:
        profile = WatchProfile(organization_id=organization.id, **values)
        db.add(profile)
    else:
        for field, value in values.items():
            setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile
