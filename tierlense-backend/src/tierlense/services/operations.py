"""Autonomous operations services: scheduling, change detection, snapshots and supplier alternatives."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from tierlense.models import (
    DiscoveredSource,
    DisruptionEvent,
    DisruptionLikelihoodAssessment,
    EvidenceChange,
    EvidenceDocument,
    InvestigationFinding,
    InvestigationJob,
    InvestigationSchedule,
    InvestigationSnapshot,
    InvestigationSource,
    Organization,
    SupplierRecommendation,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.schemas.operations import AlternativeSupplierRequest
from tierlense.services.disruption_assessment import assess_disruption_likelihood


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_schedule(db: Session, organization: Organization, *, interval_minutes: int = 1440) -> InvestigationSchedule:
    schedule = db.scalar(select(InvestigationSchedule).where(InvestigationSchedule.organization_id == organization.id))
    if schedule is None:
        now = utc_now()
        schedule = InvestigationSchedule(
            organization_id=organization.id,
            enabled=True,
            interval_minutes=interval_minutes,
            next_run_at=now + timedelta(minutes=interval_minutes),
        )
        db.add(schedule)
        db.flush()
    return schedule


def configure_schedule(
    db: Session, organization: Organization, *, enabled: bool, interval_minutes: int
) -> InvestigationSchedule:
    if not 15 <= interval_minutes <= 10080:
        raise ValueError("interval_minutes must be between 15 and 10080")
    schedule = ensure_schedule(db, organization, interval_minutes=interval_minutes)
    schedule.enabled = enabled
    schedule.interval_minutes = interval_minutes
    schedule.next_run_at = utc_now() + timedelta(minutes=interval_minutes)
    schedule.updated_at = utc_now()
    db.flush()
    return schedule


def enqueue_due_scheduled_jobs(session_factory, *, now: datetime | None = None) -> list[UUID]:
    """Enqueue at most one due scan per organization; coalesce overdue intervals."""
    current = now or utc_now()
    queued: list[UUID] = []
    with session_factory() as db:
        schedules = list(db.scalars(
            select(InvestigationSchedule)
            .where(InvestigationSchedule.enabled.is_(True), InvestigationSchedule.next_run_at <= current)
            .order_by(InvestigationSchedule.next_run_at.asc())
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all())
        for schedule in schedules:
            active_job = db.scalar(select(InvestigationJob.id).where(
                InvestigationJob.organization_id == schedule.organization_id,
                InvestigationJob.status.in_(["queued", "running"]),
            ).limit(1))
            # Do not enqueue a backlog of missed intervals; shift the next window forward.
            schedule.next_run_at = current + timedelta(minutes=schedule.interval_minutes)
            schedule.updated_at = current
            if active_job is not None:
                continue
            job = InvestigationJob(
                organization_id=schedule.organization_id,
                job_type="scheduled_scan",
                status="queued",
                scheduled_at=current,
                attempt_count=0,
                progress_message="Recurring scan queued by schedule.",
            )
            db.add(job)
            db.flush()
            schedule.last_job_id = job.id
            schedule.last_enqueued_at = current
            queued.append(job.id)
        db.commit()
    return queued


def record_successful_schedule_run(db: Session, job: InvestigationJob, *, now: datetime | None = None) -> None:
    current = now or utc_now()
    schedule = db.scalar(select(InvestigationSchedule).where(InvestigationSchedule.organization_id == job.organization_id))
    if schedule is not None and job.status == "completed":
        schedule.last_success_at = current
        schedule.updated_at = current


def create_investigation_snapshot(db: Session, job: InvestigationJob, *, now: datetime | None = None) -> InvestigationSnapshot:
    current = now or utc_now()
    source_links = list(db.scalars(select(InvestigationSource).where(InvestigationSource.job_id == job.id)).all())
    document_ids = sorted({str(link.evidence_document_id) for link in source_links if link.evidence_document_id})
    findings = list(db.scalars(select(InvestigationFinding).where(InvestigationFinding.job_id == job.id)).all())
    entities = list(db.scalars(select(SupplyChainEntity).where(SupplyChainEntity.organization_id == job.organization_id)).all())
    relationships = list(db.scalars(select(SupplyChainRelationship).where(SupplyChainRelationship.organization_id == job.organization_id)).all())
    disruptions = list(db.scalars(select(DisruptionEvent).where(DisruptionEvent.organization_id == job.organization_id)).all())
    assessments = list(db.scalars(select(DisruptionLikelihoodAssessment).where(DisruptionLikelihoodAssessment.organization_id == job.organization_id)).all())
    changes = list(db.scalars(select(EvidenceChange.id).where(EvidenceChange.job_id == job.id)).all())
    graph_snapshot = {
        "entities": [{
            "id": str(item.id), "name": item.name, "entity_type": item.entity_type,
            "country_code": item.country_code, "identity_status": item.identity_status,
            "is_root": item.is_root,
        } for item in entities],
        "relationships": [{
            "id": str(item.id), "source_entity_id": str(item.source_entity_id),
            "target_entity_id": str(item.target_entity_id), "relationship_type": item.relationship_type,
            "component_or_service": item.component_or_service, "ownership_percentage": item.ownership_percentage,
            "country_code": item.country_code, "validation_status": item.validation_status,
            "evidence_document_id": str(item.evidence_document_id), "source_passage": item.source_passage,
        } for item in relationships],
        "disruptions": [{
            "id": str(item.id), "affected_entity_id": str(item.affected_entity_id),
            "event_type": item.event_type, "event_status": item.event_status,
            "severity": item.severity, "validation_status": item.validation_status,
            "evidence_document_id": str(item.evidence_document_id), "source_passage": item.source_passage,
        } for item in disruptions],
        "risk_assessments": [{
            "id": str(item.id), "entity_id": str(item.entity_id),
            "experimental_index": item.experimental_index, "band": item.band,
            "is_experimental": item.is_experimental, "is_calibrated": item.is_calibrated,
            "assessed_at": item.assessed_at.isoformat(),
        } for item in assessments],
    }
    snapshot = db.scalar(select(InvestigationSnapshot).where(InvestigationSnapshot.job_id == job.id))
    values = {
        "organization_id": job.organization_id,
        "job_id": job.id,
        "snapshot_at": current,
        "job_type": job.job_type,
        "result_summary": dict(job.result_summary or {}),
        "evidence_document_ids": document_ids,
        "finding_ids": sorted(str(item.id) for item in findings),
        "graph_entity_ids": sorted(str(item.id) for item in entities),
        "graph_relationship_ids": sorted(str(item.id) for item in relationships),
        "disruption_event_ids": sorted(str(item.id) for item in disruptions),
        "risk_assessment_ids": sorted(str(item.id) for item in assessments),
        "graph_snapshot": graph_snapshot,
        "evidence_change_ids": sorted(str(item) for item in changes),
    }
    if snapshot is None:
        snapshot = InvestigationSnapshot(**values)
        db.add(snapshot)
    else:
        for key, value in values.items():
            setattr(snapshot, key, value)
    db.flush()
    record_successful_schedule_run(db, job, now=current)
    return snapshot


def reassess_pending_evidence_changes(db: Session, job_id: UUID) -> list[UUID]:
    """Create new experimental assessments for entities touched by a changed source."""
    from tierlense.services.supply_chain import DEPENDENCY_EDGE_TYPES

    changes = list(db.scalars(select(EvidenceChange).where(
        EvidenceChange.job_id == job_id,
        EvidenceChange.reassessment_status == "pending",
    ).order_by(EvidenceChange.detected_at.asc())).all())
    assessment_ids: list[UUID] = []
    for change in changes:
        affected_ids: set[UUID] = set()
        old_doc_ids = [item for item in (change.previous_document_id,) if item is not None]
        for doc_id in old_doc_ids:
            edges = list(db.scalars(select(SupplyChainRelationship).where(
                SupplyChainRelationship.organization_id == change.organization_id,
                SupplyChainRelationship.evidence_document_id == doc_id,
                SupplyChainRelationship.relationship_type.in_(DEPENDENCY_EDGE_TYPES),
            )).all())
            for edge in edges:
                affected_ids.update([edge.source_entity_id, edge.target_entity_id])
            events = list(db.scalars(select(DisruptionEvent).where(
                DisruptionEvent.organization_id == change.organization_id,
                DisruptionEvent.evidence_document_id == doc_id,
                DisruptionEvent.is_prediction.is_(False),
            )).all())
            affected_ids.update(event.affected_entity_id for event in events)
        # A changed document that is already linked to a graph edge/event also affects current evidence-backed entities.
        new_edges = list(db.scalars(select(SupplyChainRelationship).where(
            SupplyChainRelationship.organization_id == change.organization_id,
            SupplyChainRelationship.evidence_document_id == change.current_document_id,
            SupplyChainRelationship.relationship_type.in_(DEPENDENCY_EDGE_TYPES),
        )).all())
        for edge in new_edges:
            affected_ids.update([edge.source_entity_id, edge.target_entity_id])
        new_events = list(db.scalars(select(DisruptionEvent).where(
            DisruptionEvent.organization_id == change.organization_id,
            DisruptionEvent.evidence_document_id == change.current_document_id,
            DisruptionEvent.is_prediction.is_(False),
        )).all())
        affected_ids.update(event.affected_entity_id for event in new_events)

        # A previously verified claim tied to an older content version is retained
        # for history but downgraded for current decisions until revalidated against
        # the new document. Never erase the previous evidence record.
        for doc_id in old_doc_ids:
            stale_edges = list(db.scalars(select(SupplyChainRelationship).where(
                SupplyChainRelationship.organization_id == change.organization_id,
                SupplyChainRelationship.evidence_document_id == doc_id,
                SupplyChainRelationship.validation_status == "passage_verified",
            )).all())
            for stale_edge in stale_edges:
                stale_edge.validation_status = "needs_review"
                stale_edge.attributes = {
                    **(stale_edge.attributes or {}),
                    "evidence_changed": True,
                    "evidence_change_id": str(change.id),
                    "superseded_by_document_id": str(change.current_document_id),
                }
            stale_events = list(db.scalars(select(DisruptionEvent).where(
                DisruptionEvent.organization_id == change.organization_id,
                DisruptionEvent.evidence_document_id == doc_id,
                DisruptionEvent.validation_status == "passage_verified",
            )).all())
            for stale_event in stale_events:
                stale_event.validation_status = "needs_review"
                stale_event.updated_at = utc_now()

        ids_for_change: list[str] = []
        for entity_id in sorted(affected_ids, key=str):
            organization = db.get(Organization, change.organization_id)
            if organization is None:
                continue
            assessment = assess_disruption_likelihood(db, organization, entity_id)
            assessment.inputs = {
                **(assessment.inputs or {}),
                "trigger": "evidence_content_changed",
                "evidence_change_id": str(change.id),
                "previous_document_id": str(change.previous_document_id) if change.previous_document_id else None,
                "current_document_id": str(change.current_document_id),
            }
            assessment_ids.append(assessment.id)
            ids_for_change.append(str(assessment.id))
        change.reassessment_status = "completed"
        change.reassessment_details = {
            "affected_entity_ids": sorted(str(item) for item in affected_ids),
            "assessment_ids": ids_for_change,
            "note": "Experimental assessments were appended; historical assessments were not overwritten.",
        }
    db.flush()
    return assessment_ids


def list_evidence_changes(db: Session, organization_id: UUID, *, limit: int, offset: int):
    base = select(EvidenceChange).where(EvidenceChange.organization_id == organization_id)
    rows = list(db.scalars(base.order_by(EvidenceChange.detected_at.desc()).limit(limit).offset(offset)).all())
    from sqlalchemy import func
    total = int(db.scalar(select(func.count(EvidenceChange.id)).where(EvidenceChange.organization_id == organization_id)) or 0)
    return rows, total


def _tokens(text: str | None) -> set[str]:
    stop = {"and", "or", "for", "the", "a", "an", "of", "to", "with", "in", "by", "from", "service", "component"}
    return {token for token in re.findall(r"[a-z0-9]+", (text or "").casefold()) if len(token) > 1 and token not in stop}


def recommend_alternatives(db: Session, organization: Organization, affected_entity_id: UUID, payload: AlternativeSupplierRequest) -> SupplierRecommendation:
    affected = db.get(SupplyChainEntity, affected_entity_id)
    if affected is None or affected.organization_id != organization.id:
        raise LookupError("Affected entity not found in this organization's graph")

    from tierlense.services.supply_chain import DEPENDENCY_EDGE_TYPES, passage_is_in_document
    role_edges = {"supplies", "provides_component", "provides_service", "manufactures_for", "distributes_to"}
    edges = list(db.scalars(select(SupplyChainRelationship).where(
        SupplyChainRelationship.organization_id == organization.id,
        SupplyChainRelationship.target_entity_id == affected_entity_id,
        SupplyChainRelationship.relationship_type.in_(role_edges),
        SupplyChainRelationship.validation_status == "passage_verified",
    ).order_by(SupplyChainRelationship.created_at.desc())).all())
    required_tokens = _tokens(payload.required_function)
    required_countries = set(payload.required_country_codes)
    excluded_countries = set(payload.excluded_country_codes)
    candidates: dict[str, dict[str, Any]] = {}

    for edge in edges:
        candidate = db.get(SupplyChainEntity, edge.source_entity_id)
        document = db.get(EvidenceDocument, edge.evidence_document_id)
        if candidate is None or document is None or candidate.organization_id != organization.id:
            continue
        if candidate.is_root:
            continue
        source = db.get(DiscoveredSource, document.source_id)
        if not source or not edge.source_passage or not passage_is_in_document(edge.source_passage, document.content_text):
            continue
        country = (candidate.country_code or edge.country_code or "").upper() or None
        if country and country in excluded_countries:
            continue
        if required_countries and country and country not in required_countries:
            continue
        function_text = edge.component_or_service or ""
        function_tokens = _tokens(function_text)
        intersection = required_tokens & function_tokens
        if not required_tokens or not function_tokens or not intersection:
            continue
        coverage = len(intersection) / len(required_tokens)
        jaccard = len(intersection) / max(1, len(required_tokens | function_tokens))
        exact = " ".join(re.findall(r"[a-z0-9]+", payload.required_function.casefold())) == " ".join(re.findall(r"[a-z0-9]+", function_text.casefold()))
        score = 1.0 if exact else round(0.65 * coverage + 0.35 * jaccard, 3)
        missing: list[str] = []
        rationale = [f"Candidate is linked to the affected entity by a passage-verified '{edge.relationship_type}' relationship."]
        if candidate.identity_status not in {"verified", "monitored_root"}:
            missing.append(f"Candidate identity status is '{candidate.identity_status}'; independent identity resolution remains outstanding.")
        if exact:
            rationale.append("The recorded component/service description matches the requested function exactly after basic text normalization.")
        else:
            rationale.append(f"Function comparison shares {len(intersection)} of {len(required_tokens)} required terms; human compatibility review is required.")
            missing.append("Detailed technical, capacity and qualification compatibility is not established by text overlap alone.")
        if country is None:
            missing.append("Candidate country is unknown in the current graph.")
        if required_countries and country is None:
            missing.append("Required country constraint cannot be verified because the candidate country is unknown.")
        if payload.required_role:
            recorded_role = str((candidate.attributes or {}).get("supplier_role") or "")
            if recorded_role and recorded_role.casefold() != payload.required_role.casefold():
                continue
            if not recorded_role:
                missing.append("Supplier role is not explicitly recorded; role compatibility remains unverified.")
        status = "potential_match" if exact and not missing else "conditional_match"
        candidate_key = str(candidate.id)
        row = {
            "entity_id": candidate.id,
            "entity_name": candidate.name,
            "entity_type": candidate.entity_type,
            "identity_status": candidate.identity_status,
            "country_code": country,
            "match_index": score,
            "match_status": status,
            "matched_function": function_text,
            "relationship_id": edge.id,
            "evidence_document_id": document.id,
            "evidence_url": source.canonical_url,
            "source_passage": edge.source_passage,
            "rationale": rationale,
            "missing_information": missing,
        }
        previous = candidates.get(candidate_key)
        if previous is None or row["match_index"] > previous["match_index"]:
            candidates[candidate_key] = row

    ranked = sorted(candidates.values(), key=lambda item: (item["match_status"] != "potential_match", -item["match_index"], item["entity_name"]))[:payload.limit]
    result_status = "potential_matches_found" if any(item["match_status"] == "potential_match" for item in ranked) else "conditional_matches_only" if ranked else "insufficient_evidence"
    result = SupplierRecommendation(
        organization_id=organization.id,
        affected_entity_id=affected.id,
        required_function=payload.required_function,
        required_role=payload.required_role,
        constraints={"required_country_codes": sorted(required_countries), "excluded_country_codes": sorted(excluded_countries), "limit": payload.limit},
        candidates=[{key: str(value) if isinstance(value, UUID) else value for key, value in item.items()} for item in ranked],
        result_status=result_status,
        scoring_version="deterministic-function-match-v1",
    )
    db.add(result)
    db.flush()
    return result
