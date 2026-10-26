"""Supply-chain graph, disruption status, impact and evidence APIs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tierlense.db.session import get_db
from tierlense.models import (
    DiscoveredSource,
    DisruptionEvent,
    DisruptionLikelihoodAssessment,
    EvidenceDocument,
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.schemas.supply_chain import (
    DisruptionEventCreate,
    DisruptionEventCreateResult,
    DisruptionEventList,
    DisruptionEventRead,
    DisruptionLikelihoodRead,
    DownstreamImpactRead,
    EvidenceInspectionRead,
    GraphNode,
    GraphRelationship,
    SupplyChainEntityCreate,
    SupplyChainEntityCreateResult,
    SupplyChainEntityList,
    SupplyChainEntityRead,
    SupplyChainGraphRead,
    SupplyChainRelationshipCreate,
    SupplyChainRelationshipCreateResult,
    SupplyChainRelationshipList,
    SupplyChainRelationshipRead,
)
from tierlense.services.disruption_assessment import assess_disruption_likelihood
from tierlense.services.supply_chain import (
    calculate_downstream_impact,
    create_disruption_event,
    create_relationship,
    ensure_root_entity,
    evidence_document_read,
    traverse_graph,
    upsert_entity,
)

router = APIRouter(prefix="/supply-chain/organizations/{organization_id}", tags=["supply-chain graph"])


def _organization(db: Session, organization_id: UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def _relationship_read(db: Session, edge: SupplyChainRelationship) -> SupplyChainRelationshipRead:
    source = db.get(SupplyChainEntity, edge.source_entity_id)
    target = db.get(SupplyChainEntity, edge.target_entity_id)
    document = db.get(EvidenceDocument, edge.evidence_document_id)
    source_record = db.get(DiscoveredSource, document.source_id) if document else None
    return SupplyChainRelationshipRead(
        id=edge.id,
        organization_id=edge.organization_id,
        source_entity_id=edge.source_entity_id,
        source_entity_name=source.name if source else "Unknown entity",
        target_entity_id=edge.target_entity_id,
        target_entity_name=target.name if target else "Unknown entity",
        relationship_type=edge.relationship_type,
        component_or_service=edge.component_or_service,
        ownership_percentage=edge.ownership_percentage,
        is_state_owned=edge.is_state_owned,
        country_code=edge.country_code,
        as_of_date=edge.as_of_date,
        confidence=edge.confidence,
        validation_status=edge.validation_status,
        evidence_document_id=edge.evidence_document_id,
        evidence_url=source_record.canonical_url if source_record else "",
        source_finding_id=edge.source_finding_id,
        source_passage=edge.source_passage,
        attributes=edge.attributes or {},
        created_at=edge.created_at,
    )


def _event_read(db: Session, event: DisruptionEvent) -> DisruptionEventRead:
    entity = db.get(SupplyChainEntity, event.affected_entity_id)
    document = db.get(EvidenceDocument, event.evidence_document_id)
    source = db.get(DiscoveredSource, document.source_id) if document else None
    return DisruptionEventRead(
        id=event.id,
        organization_id=event.organization_id,
        affected_entity_id=event.affected_entity_id,
        affected_entity_name=entity.name if entity else "Unknown entity",
        event_type=event.event_type,
        event_status=event.event_status,
        severity=event.severity,
        country_code=event.country_code,
        event_date=event.event_date,
        summary=event.summary,
        confidence=event.confidence,
        validation_status=event.validation_status,
        evidence_document_id=event.evidence_document_id,
        evidence_url=source.canonical_url if source else "",
        source_finding_id=event.source_finding_id,
        source_passage=event.source_passage,
        is_prediction=event.is_prediction,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


@router.post("/entities", response_model=SupplyChainEntityCreateResult, status_code=status.HTTP_201_CREATED,
             summary="Resolve or create an entity in the organization's graph")
def post_entity(
    organization_id: UUID, payload: SupplyChainEntityCreate, db: Session = Depends(get_db)
) -> SupplyChainEntityCreateResult:
    organization = _organization(db, organization_id)
    try:
        entity, action = upsert_entity(
            db, organization, name=payload.name, entity_type=payload.entity_type,
            country_code=payload.country_code, aliases=payload.aliases, attributes=payload.attributes,
            root=False,
        )
        db.commit()
        db.refresh(entity)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    note = (
        "Exact normalized-name or alias match reused; no duplicate entity created."
        if action == "matched_exact" else
        "Entity created without fuzzy auto-merging. Any similar-name candidates are flagged for human review."
    )
    return SupplyChainEntityCreateResult(
        entity=SupplyChainEntityRead.model_validate(entity), resolution_action=action, note=note
    )


@router.get("/entities", response_model=SupplyChainEntityList, summary="List graph entities")
def get_entities(
    organization_id: UUID,
    entity_type: str | None = Query(default=None, max_length=32),
    country_code: str | None = Query(default=None, min_length=2, max_length=2),
    q: str | None = Query(default=None, max_length=500),
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> SupplyChainEntityList:
    organization = _organization(db, organization_id)
    ensure_root_entity(db, organization)
    db.commit()
    predicates = [SupplyChainEntity.organization_id == organization_id]
    if entity_type:
        predicates.append(SupplyChainEntity.entity_type == entity_type)
    if country_code:
        predicates.append(SupplyChainEntity.country_code == country_code.upper())
    if q:
        predicates.append(SupplyChainEntity.name.ilike(f"%{q.strip()}%"))
    rows = list(db.scalars(select(SupplyChainEntity).where(*predicates).order_by(SupplyChainEntity.is_root.desc(), SupplyChainEntity.name).limit(limit).offset(offset)).all())
    total = int(db.scalar(select(func.count(SupplyChainEntity.id)).where(*predicates)) or 0)
    return SupplyChainEntityList(items=[SupplyChainEntityRead.model_validate(row) for row in rows], total=total)


@router.post("/relationships", response_model=SupplyChainRelationshipCreateResult, status_code=status.HTTP_201_CREATED,
             summary="Create an evidence-backed directed relationship")
def post_relationship(
    organization_id: UUID, payload: SupplyChainRelationshipCreate, db: Session = Depends(get_db)
) -> SupplyChainRelationshipCreateResult:
    organization = _organization(db, organization_id)
    try:
        edge, created = create_relationship(db, organization, payload)
        db.commit()
        db.refresh(edge)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SupplyChainRelationshipCreateResult(
        relationship=_relationship_read(db, edge),
        created=created,
        note=("Relationship persisted with a source-passage check." if created else "Matching evidence-backed relationship already existed; reused it."),
    )


@router.get("/relationships", response_model=SupplyChainRelationshipList, summary="List evidence-backed relationships")
def get_relationships(
    organization_id: UUID,
    relationship_type: str | None = Query(default=None, max_length=48),
    min_ownership_percentage: float | None = Query(default=None, ge=0.0, le=100.0),
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> SupplyChainRelationshipList:
    _organization(db, organization_id)
    predicates = [SupplyChainRelationship.organization_id == organization_id]
    if relationship_type:
        predicates.append(SupplyChainRelationship.relationship_type == relationship_type)
    if min_ownership_percentage is not None:
        predicates.extend([
            SupplyChainRelationship.relationship_type == "owns",
            SupplyChainRelationship.ownership_percentage >= min_ownership_percentage,
        ])
    query = select(SupplyChainRelationship).where(*predicates)
    rows = list(db.scalars(query.order_by(SupplyChainRelationship.created_at.desc()).limit(limit).offset(offset)).all())
    total = int(db.scalar(select(func.count(SupplyChainRelationship.id)).where(*predicates)) or 0)
    return SupplyChainRelationshipList(items=[_relationship_read(db, row) for row in rows], total=total)


@router.get("/graph", response_model=SupplyChainGraphRead, summary="Retrieve a multi-tier supply-chain graph")
def get_graph(
    organization_id: UUID,
    root_entity_id: UUID | None = None,
    direction: str = Query(default="both", pattern="^(upstream|downstream|both)$"),
    max_depth: Annotated[int, Query(ge=1, le=8)] = 4,
    country_code: str | None = Query(default=None, min_length=2, max_length=2),
    include_ownership: bool = True,
    db: Session = Depends(get_db),
) -> SupplyChainGraphRead:
    organization = _organization(db, organization_id)
    try:
        result = traverse_graph(
            db, organization, root_entity_id=root_entity_id, direction=direction,
            max_depth=max_depth, country_code=country_code, include_ownership=include_ownership,
        )
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    nodes = [
        GraphNode(entity=SupplyChainEntityRead.model_validate(item["entity"]), depth=item["depth"], path_entity_ids=item["path_entity_ids"])
        for item in result["nodes"]
    ]
    relationships = []
    for edge in result["relationships"]:
        # Graph reads share the same evidence details as the relationship endpoint.
        rich = _relationship_read(db, edge)
        relationships.append(GraphRelationship(
            id=rich.id, source_entity_id=rich.source_entity_id, source_entity_name=rich.source_entity_name,
            target_entity_id=rich.target_entity_id, target_entity_name=rich.target_entity_name,
            relationship_type=rich.relationship_type, component_or_service=rich.component_or_service,
            ownership_percentage=rich.ownership_percentage, country_code=rich.country_code,
            validation_status=rich.validation_status, evidence_document_id=rich.evidence_document_id,
            source_passage=rich.source_passage,
        ))
    return SupplyChainGraphRead(
        organization_id=organization_id, root_entity_id=result["root_entity_id"], direction=direction,
        max_depth=max_depth, tier_definition=result["tier_definition"], nodes=nodes, relationships=relationships,
    )


@router.post("/disruptions", response_model=DisruptionEventCreateResult, status_code=status.HTTP_201_CREATED,
             summary="Record a source-linked disruption event or risk signal")
def post_disruption(
    organization_id: UUID, payload: DisruptionEventCreate, db: Session = Depends(get_db)
) -> DisruptionEventCreateResult:
    organization = _organization(db, organization_id)
    try:
        event, created = create_disruption_event(db, organization, payload)
        db.commit()
        db.refresh(event)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DisruptionEventCreateResult(
        event=_event_read(db, event), created=created,
        note=("Source-linked disruption event saved after exact-passage validation." if created else "Matching source-linked event already existed; reused it."),
    )


@router.get("/disruptions", response_model=DisruptionEventList, summary="List source-linked disruption events")
def get_disruptions(
    organization_id: UUID,
    entity_id: UUID | None = None,
    event_status: str | None = Query(default=None, max_length=32),
    event_type: str | None = Query(default=None, max_length=48),
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> DisruptionEventList:
    _organization(db, organization_id)
    predicates = [DisruptionEvent.organization_id == organization_id]
    if entity_id:
        entity = db.get(SupplyChainEntity, entity_id)
        if entity is None or entity.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Entity not found in this organization's graph")
        predicates.append(DisruptionEvent.affected_entity_id == entity_id)
    if event_status:
        predicates.append(DisruptionEvent.event_status == event_status)
    if event_type:
        predicates.append(DisruptionEvent.event_type == event_type)
    rows = list(db.scalars(select(DisruptionEvent).where(*predicates).order_by(DisruptionEvent.created_at.desc()).limit(limit).offset(offset)).all())
    total = int(db.scalar(select(func.count(DisruptionEvent.id)).where(*predicates)) or 0)
    return DisruptionEventList(items=[_event_read(db, row) for row in rows], total=total)


@router.get("/disruptions/{event_id}", response_model=DisruptionEventRead, summary="Inspect disruption status and evidence")
def get_disruption(
    organization_id: UUID, event_id: UUID, db: Session = Depends(get_db)
) -> DisruptionEventRead:
    _organization(db, organization_id)
    event = db.scalar(select(DisruptionEvent).where(
        DisruptionEvent.id == event_id, DisruptionEvent.organization_id == organization_id,
    ))
    if event is None:
        raise HTTPException(status_code=404, detail="Disruption event not found")
    return _event_read(db, event)


@router.get("/impact", response_model=DownstreamImpactRead, summary="Calculate downstream dependency exposure")
def get_impact(
    organization_id: UUID,
    entity_id: UUID,
    event_id: UUID | None = None,
    max_depth: Annotated[int, Query(ge=1, le=8)] = 4,
    db: Session = Depends(get_db),
) -> DownstreamImpactRead:
    organization = _organization(db, organization_id)
    if event_id is not None:
        event = db.scalar(select(DisruptionEvent).where(
            DisruptionEvent.id == event_id,
            DisruptionEvent.organization_id == organization_id,
            DisruptionEvent.affected_entity_id == entity_id,
        ))
        if event is None:
            raise HTTPException(status_code=404, detail="Disruption event not found for the selected entity")
    try:
        result = calculate_downstream_impact(db, organization, entity_id, max_depth=max_depth, event_id=event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    converted = []
    for item in result["affected_entities"]:
        converted.append({
            **item,
            "entity": SupplyChainEntityRead.model_validate(item["entity"]),
        })
    return DownstreamImpactRead(**{**result, "affected_entities": converted})


@router.get("/entities/{entity_id}/likelihood", response_model=DisruptionLikelihoodRead,
            summary="Calculate an experimental disruption-signal index")
def get_likelihood(
    organization_id: UUID, entity_id: UUID, db: Session = Depends(get_db)
) -> DisruptionLikelihoodRead:
    organization = _organization(db, organization_id)
    try:
        assessment = assess_disruption_likelihood(db, organization, entity_id)
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    entity = db.get(SupplyChainEntity, entity_id)
    return DisruptionLikelihoodRead(
        id=assessment.id,
        organization_id=assessment.organization_id,
        entity_id=assessment.entity_id,
        entity_name=entity.name if entity else "Unknown entity",
        experimental_index=assessment.experimental_index,
        band=assessment.band,
        rationale=assessment.rationale or [],
        inputs=assessment.inputs or {},
        model_version=assessment.model_version,
        assessed_at=assessment.assessed_at,
    )


@router.get("/evidence/{document_id}", response_model=EvidenceInspectionRead,
            summary="Inspect the source document and its linked evidence passages")
def get_evidence(
    organization_id: UUID, document_id: UUID, db: Session = Depends(get_db)
) -> EvidenceInspectionRead:
    _organization(db, organization_id)
    result = evidence_document_read(db, organization_id, document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evidence document not found for this organization")
    return EvidenceInspectionRead(**result)
