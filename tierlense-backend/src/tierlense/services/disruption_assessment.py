"""Separate experimental disruption-likelihood signal assessment service.

The current implementation is a transparent, rule-based index. It is not a calibrated
probability and must remain experimental until tested against representative labels.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tierlense.models import (
    DisruptionEvent,
    DisruptionLikelihoodAssessment,
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.services.supply_chain import DEPENDENCY_EDGE_TYPES


def assess_disruption_likelihood(
    db: Session, organization: Organization, entity_id: UUID
) -> DisruptionLikelihoodAssessment:
    entity = db.get(SupplyChainEntity, entity_id)
    if entity is None or entity.organization_id != organization.id:
        raise LookupError("Entity not found in this organization's graph")
    events = list(db.scalars(select(DisruptionEvent).where(
        DisruptionEvent.organization_id == organization.id,
        DisruptionEvent.affected_entity_id == entity.id,
        DisruptionEvent.validation_status == "passage_verified",
        DisruptionEvent.is_prediction.is_(False),
    )).all())
    downstream_edges = list(db.scalars(select(SupplyChainRelationship).where(
        SupplyChainRelationship.organization_id == organization.id,
        SupplyChainRelationship.source_entity_id == entity.id,
        SupplyChainRelationship.relationship_type.in_(DEPENDENCY_EDGE_TYPES),
        SupplyChainRelationship.validation_status == "passage_verified",
    )).all())
    rationale: list[str] = []
    inputs = {"verified_event_count": len(events), "downstream_dependency_edges": len(downstream_edges), "evidence_available": bool(events)}
    if not events:
        score = 0.0
        band = "insufficient_evidence"
        rationale.append("No passage-verified disruption events are linked to this entity; insufficient evidence for an evidence-derived signal index.")
    else:
        signal_events = sum(1 for event in events if event.event_status in {"risk_signal", "forecast"})
        severe_events = sum(1 for event in events if (event.severity or 0) >= 4)
        score = min(100.0, 10.0 + min(20.0 * len(events), 50.0) + min(10.0 * signal_events, 20.0) + min(5.0 * severe_events, 15.0) + min(2.0 * len(downstream_edges), 15.0))
        band = "low_signal" if score < 25 else "guarded_signal" if score < 50 else "elevated_signal" if score < 75 else "high_signal"
        rationale.append(f"{len(events)} passage-verified source-linked event(s) affect this entity.")
        if signal_events:
            rationale.append(f"{signal_events} event(s) are marked as source-reported forecasts or risk signals.")
        if severe_events:
            rationale.append(f"{severe_events} event(s) have source-assigned severity of 4 or 5.")
        if downstream_edges:
            rationale.append(f"{len(downstream_edges)} verified downstream dependency edge(s) indicate exposure concentration.")
    assessment = DisruptionLikelihoodAssessment(
        organization_id=organization.id,
        entity_id=entity.id,
        experimental_index=round(score, 2),
        band=band,
        rationale=rationale,
        inputs=inputs,
        model_version="experimental-rules-v1",
        is_experimental=True,
        is_calibrated=False,
    )
    db.add(assessment)
    db.flush()
    return assessment


