"""Supply-chain graph services: exact entity resolution, provenance, traversal and assessments."""

from __future__ import annotations

import hashlib
import re
from collections import deque
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tierlense.models import (
    DiscoveredSource,
    DisruptionEvent,
    DisruptionLikelihoodAssessment,
    EvidenceDocument,
    InvestigationFinding,
    InvestigationJob,
    InvestigationSource,
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
)

ENTITY_TYPES = {"organization", "facility", "component", "service", "country", "person", "other"}
RELATIONSHIP_TYPES = {
    "supplies", "provides_component", "provides_service", "owns", "operates", "located_in",
    "manufactures_for", "distributes_to", "depends_on", "board_relationship", "country_dependency",
    "other_dependency",
}
DEPENDENCY_EDGE_TYPES = {
    "supplies", "provides_component", "provides_service", "manufactures_for", "distributes_to",
    "depends_on", "other_dependency", "country_dependency", "owns", "located_in",
}


def normalize_entity_name(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()
    legal_suffixes = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "llc", "plc"}
    tokens = text.split()
    while tokens and tokens[-1] in legal_suffixes:
        tokens.pop()
    return " ".join(tokens)


def normalize_passage(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def passage_is_in_document(passage: str, content: str) -> bool:
    normalized = normalize_passage(passage)
    return len(normalized) >= 12 and normalized in normalize_passage(content)


def _fingerprint(*values: str) -> str:
    material = "|".join(values)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_organization(db: Session, organization_id: UUID) -> Organization | None:
    return db.get(Organization, organization_id)


def ensure_root_entity(db: Session, organization: Organization) -> SupplyChainEntity:
    entity = db.scalar(
        select(SupplyChainEntity).where(
            SupplyChainEntity.organization_id == organization.id,
            SupplyChainEntity.is_root.is_(True),
        )
    )
    if entity is not None:
        if not entity.country_code and organization.country_code:
            entity.country_code = organization.country_code.upper()
        return entity

    normalized = normalize_entity_name(organization.name)
    entity = db.scalar(
        select(SupplyChainEntity).where(
            SupplyChainEntity.organization_id == organization.id,
            SupplyChainEntity.normalized_name == normalized,
            SupplyChainEntity.entity_type == "organization",
        )
    )
    if entity is None:
        entity = SupplyChainEntity(
            organization_id=organization.id,
            name=organization.name,
            normalized_name=normalized,
            entity_type="organization",
            country_code=organization.country_code.upper() if organization.country_code else None,
            aliases=[],
            identity_status="monitored_root",
            resolution_confidence=1.0,
            is_root=True,
            attributes={"root_source": "organization_registry"},
        )
        db.add(entity)
        db.flush()
    else:
        entity.is_root = True
        entity.identity_status = "monitored_root"
    return entity


def _exact_entity_match(
    db: Session, organization_id: UUID, name: str, entity_type: str
) -> SupplyChainEntity | None:
    normalized = normalize_entity_name(name)
    if not normalized:
        return None
    candidates = list(
        db.scalars(
            select(SupplyChainEntity).where(
                SupplyChainEntity.organization_id == organization_id,
                SupplyChainEntity.entity_type == entity_type,
            )
        ).all()
    )
    for candidate in candidates:
        if candidate.normalized_name == normalized:
            return candidate
        for alias in candidate.aliases or []:
            if normalize_entity_name(alias) == normalized:
                return candidate
    return None


def upsert_entity(
    db: Session,
    organization: Organization,
    *,
    name: str,
    entity_type: str = "organization",
    country_code: str | None = None,
    aliases: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    root: bool = False,
) -> tuple[SupplyChainEntity, str]:
    if entity_type not in ENTITY_TYPES:
        raise ValueError("Unsupported entity_type")
    cleaned = (name or "").strip()
    normalized = normalize_entity_name(cleaned)
    if not normalized:
        raise ValueError("Entity name must contain at least one letter or number")
    existing_root = ensure_root_entity(db, organization)
    if normalize_entity_name(existing_root.name) == normalized and entity_type == "organization":
        return existing_root, "matched_exact"

    entity = _exact_entity_match(db, organization.id, cleaned, entity_type)
    clean_aliases = list(dict.fromkeys(alias.strip() for alias in (aliases or []) if alias and alias.strip()))
    if entity:
        combined = list(entity.aliases or [])
        for alias in clean_aliases:
            if normalize_entity_name(alias) not in {normalize_entity_name(item) for item in combined}:
                combined.append(alias)
        entity.aliases = combined
        if not entity.country_code and country_code:
            entity.country_code = country_code.upper()
        if attributes:
            entity.attributes = {**(entity.attributes or {}), **attributes}
        return entity, "matched_exact"

    root_entity = ensure_root_entity(db, organization) if root else None
    if root_entity is not None:
        return root_entity, "matched_exact"

    possible_matches: list[tuple[float, SupplyChainEntity]] = []
    for candidate in db.scalars(
        select(SupplyChainEntity).where(
            SupplyChainEntity.organization_id == organization.id,
            SupplyChainEntity.entity_type == entity_type,
        )
    ).all():
        similarity = SequenceMatcher(None, normalized, candidate.normalized_name).ratio()
        if similarity >= 0.90:
            possible_matches.append((similarity, candidate))
    entity = SupplyChainEntity(
        organization_id=organization.id,
        name=cleaned,
        normalized_name=normalized,
        entity_type=entity_type,
        country_code=country_code.upper() if country_code else None,
        aliases=clean_aliases,
        identity_status="needs_review" if possible_matches else "unverified",
        resolution_confidence=0.0,
        is_root=False,
        attributes={**(attributes or {}), **({"possible_match_ids": [str(item.id) for _, item in possible_matches[:5]]} if possible_matches else {})},
    )
    db.add(entity)
    db.flush()
    return entity, "created_needs_review"


def _document_for_organization(
    db: Session, organization_id: UUID, document_id: UUID
) -> EvidenceDocument | None:
    document = db.scalar(
        select(EvidenceDocument)
        .join(InvestigationSource, InvestigationSource.evidence_document_id == EvidenceDocument.id)
        .join(InvestigationJob, InvestigationJob.id == InvestigationSource.job_id)
        .where(
            EvidenceDocument.id == document_id,
            InvestigationJob.organization_id == organization_id,
        )
        .limit(1)
    )
    return document


def _source_url(db: Session, document: EvidenceDocument) -> str:
    source = db.get(DiscoveredSource, document.source_id)
    return source.canonical_url if source else ""


def create_relationship(
    db: Session, organization: Organization, payload: Any
) -> tuple[SupplyChainRelationship, bool]:
    source = db.get(SupplyChainEntity, payload.source_entity_id)
    target = db.get(SupplyChainEntity, payload.target_entity_id)
    if source is None or target is None or source.organization_id != organization.id or target.organization_id != organization.id:
        raise ValueError("Both relationship entities must belong to this organization's graph")
    if source.id == target.id:
        raise ValueError("Self relationships are not allowed")
    if payload.relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError("Unsupported relationship type")
    document = _document_for_organization(db, organization.id, payload.evidence_document_id)
    if document is None:
        raise ValueError("Evidence document does not belong to an investigation for this organization")
    if not passage_is_in_document(payload.source_passage, document.content_text):
        raise ValueError("source_passage must be an exact passage from the stored evidence document")
    if payload.source_finding_id is not None:
        finding = db.get(InvestigationFinding, payload.source_finding_id)
        if (
            finding is None or finding.organization_id != organization.id
            or finding.evidence_document_id != document.id
            or finding.validation_status != "passage_verified"
        ):
            raise ValueError("source_finding_id must reference a passage-verified finding from this document")
    if payload.ownership_percentage is not None and payload.relationship_type != "owns":
        raise ValueError("ownership_percentage is only valid for owns relationships")
    fingerprint = _fingerprint(
        str(organization.id), str(source.id), str(target.id), payload.relationship_type,
        str(document.id), normalize_passage(payload.source_passage),
    )
    existing = db.scalar(
        select(SupplyChainRelationship).where(
            SupplyChainRelationship.organization_id == organization.id,
            SupplyChainRelationship.fingerprint == fingerprint,
        )
    )
    if existing:
        return existing, False
    edge = SupplyChainRelationship(
        organization_id=organization.id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=payload.relationship_type,
        component_or_service=payload.component_or_service,
        ownership_percentage=payload.ownership_percentage,
        is_state_owned=payload.is_state_owned,
        country_code=payload.country_code.upper() if payload.country_code else None,
        as_of_date=payload.as_of_date,
        confidence=payload.confidence,
        validation_status="passage_verified",
        evidence_document_id=document.id,
        source_finding_id=payload.source_finding_id,
        source_passage=payload.source_passage.strip(),
        fingerprint=fingerprint,
        attributes=payload.attributes or {},
    )
    db.add(edge)
    db.flush()
    return edge, True


def create_disruption_event(
    db: Session, organization: Organization, payload: Any
) -> tuple[DisruptionEvent, bool]:
    entity = db.get(SupplyChainEntity, payload.affected_entity_id)
    if entity is None or entity.organization_id != organization.id:
        raise ValueError("Affected entity must belong to this organization's graph")
    document = _document_for_organization(db, organization.id, payload.evidence_document_id)
    if document is None:
        raise ValueError("Evidence document does not belong to an investigation for this organization")
    if not passage_is_in_document(payload.source_passage, document.content_text):
        raise ValueError("source_passage must be an exact passage from the stored evidence document")
    if payload.source_finding_id is not None:
        finding = db.get(InvestigationFinding, payload.source_finding_id)
        if (
            finding is None or finding.organization_id != organization.id
            or finding.evidence_document_id != document.id
            or finding.validation_status != "passage_verified"
        ):
            raise ValueError("source_finding_id must reference a passage-verified finding from this document")
    fingerprint = _fingerprint(
        str(organization.id), str(entity.id), payload.event_type, payload.event_status,
        str(document.id), normalize_passage(payload.source_passage),
    )
    existing = db.scalar(
        select(DisruptionEvent).where(
            DisruptionEvent.organization_id == organization.id,
            DisruptionEvent.fingerprint == fingerprint,
        )
    )
    if existing:
        return existing, False
    event = DisruptionEvent(
        organization_id=organization.id,
        affected_entity_id=entity.id,
        event_type=payload.event_type,
        event_status=payload.event_status,
        severity=payload.severity,
        country_code=payload.country_code.upper() if payload.country_code else None,
        event_date=payload.event_date,
        summary=payload.summary,
        confidence=payload.confidence,
        validation_status="passage_verified",
        evidence_document_id=document.id,
        source_finding_id=payload.source_finding_id,
        source_passage=payload.source_passage.strip(),
        fingerprint=fingerprint,
        # A source-reported forecast is still a cited source event, not a TierLense prediction.
        is_prediction=False,
    )
    db.add(event)
    db.flush()
    return event, True


def _guess_disruption_type(finding: InvestigationFinding, details: dict[str, Any]) -> str:
    if details.get("disruption_type"):
        return str(details["disruption_type"])
    text = f"{finding.predicate} {finding.summary}".casefold()
    rules = [
        ("cyber", "cyber_incident"), ("ransomware", "cyber_incident"),
        ("shutdown", "production_shutdown"), ("shut down", "production_shutdown"),
        ("capacity", "capacity_shortage"), ("shortage", "capacity_shortage"),
        ("labor", "labor_dispute"), ("strike", "labor_dispute"),
        ("logistics", "logistics_disruption"), ("shipping", "logistics_disruption"),
        ("regulatory", "regulatory_action"), ("sanction", "regulatory_action"),
        ("financial distress", "financial_distress"), ("bankrupt", "financial_distress"),
        ("earthquake", "natural_disaster"), ("flood", "natural_disaster"), ("fire", "natural_disaster"),
        ("outage", "operational_outage"), ("disruption", "operational_outage"),
    ]
    return next((kind for needle, kind in rules if needle in text), "other")


def materialize_verified_findings(db: Session, job_id: UUID) -> dict[str, int]:
    """Idempotently promote explicit structured metadata from passage-verified findings into graph records."""
    job = db.get(InvestigationJob, job_id)
    if job is None:
        return {"entities_created": 0, "relationships_created": 0, "events_created": 0}
    organization = db.get(Organization, job.organization_id)
    if organization is None:
        return {"entities_created": 0, "relationships_created": 0, "events_created": 0}
    ensure_root_entity(db, organization)
    counts = {"entities_created": 0, "relationships_created": 0, "events_created": 0}
    rows = list(db.scalars(select(InvestigationFinding).where(
        InvestigationFinding.job_id == job_id,
        InvestigationFinding.validation_status == "passage_verified",
    )).all())
    for finding in rows:
        details = finding.structured_details or {}
        subject_name = (finding.subject_name or "").strip()
        if not subject_name:
            continue
        subject_type = str(details.get("subject_entity_type") or "organization")
        subject, subject_action = upsert_entity(
            db, organization, name=subject_name, entity_type=subject_type,
            country_code=details.get("country_code"), root=(normalize_entity_name(subject_name) == normalize_entity_name(organization.name)),
        )
        if subject_action == "created_needs_review":
            counts["entities_created"] += 1

        if finding.finding_type == "disruption_event":
            if not finding.source_passage or not finding.evidence_document_id:
                continue
            fingerprint = _fingerprint(
                str(organization.id), str(subject.id), str(finding.id), "disruption_event"
            )
            exists = db.scalar(select(DisruptionEvent.id).where(
                DisruptionEvent.organization_id == organization.id,
                DisruptionEvent.fingerprint == fingerprint,
            ))
            if exists:
                continue
            db.add(DisruptionEvent(
                organization_id=organization.id,
                affected_entity_id=subject.id,
                event_type=_guess_disruption_type(finding, details),
                event_status=finding.event_status,
                severity=details.get("severity"),
                country_code=(details.get("country_code") or subject.country_code),
                event_date=finding.event_date,
                summary=finding.summary,
                confidence=finding.model_confidence,
                validation_status="passage_verified",
                evidence_document_id=finding.evidence_document_id,
                source_finding_id=finding.id,
                source_passage=finding.source_passage,
                fingerprint=fingerprint,
                is_prediction=False,
            ))
            counts["events_created"] += 1
            continue

        relation_type = details.get("relationship_type")
        related_name = details.get("related_entity_name")
        if finding.finding_type == "ownership_relationship" and not relation_type:
            relation_type = "owns"
        elif finding.finding_type == "technical_dependency" and not relation_type:
            relation_type = "depends_on"
        if finding.finding_type == "supplier_relationship" and not relation_type:
            # Never infer the relationship's direction from generic prose.
            continue
        if relation_type not in RELATIONSHIP_TYPES or not related_name or not finding.source_passage:
            continue
        related_type = details.get("related_entity_type")
        if related_type not in ENTITY_TYPES:
            related_type = "organization" if relation_type in {"supplies", "owns", "operates", "manufactures_for", "distributes_to"} else "component"
        related, related_action = upsert_entity(
            db, organization, name=str(related_name), entity_type=related_type,
            country_code=details.get("country_code"),
        )
        if related_action == "created_needs_review":
            counts["entities_created"] += 1
        if relation_type == "depends_on":
            # Store canonical upstream -> downstream direction: dependency/provider -> dependent.
            source_entity, target_entity = related, subject
        elif relation_type == "located_in" and related_type == "country":
            source_entity, target_entity = related, subject
        else:
            source_entity, target_entity = subject, related
        fingerprint = _fingerprint(
            str(organization.id), str(source_entity.id), str(target_entity.id), str(finding.id), str(relation_type)
        )
        exists = db.scalar(select(SupplyChainRelationship.id).where(
            SupplyChainRelationship.organization_id == organization.id,
            SupplyChainRelationship.fingerprint == fingerprint,
        ))
        if not exists:
            db.add(SupplyChainRelationship(
                organization_id=organization.id,
                source_entity_id=source_entity.id,
                target_entity_id=target_entity.id,
                relationship_type=str(relation_type),
                component_or_service=details.get("component_or_service"),
                ownership_percentage=details.get("ownership_percentage"),
                is_state_owned=details.get("is_state_owned"),
                country_code=details.get("country_code"),
                as_of_date=finding.event_date,
                confidence=finding.model_confidence,
                validation_status="passage_verified",
                evidence_document_id=finding.evidence_document_id,
                source_finding_id=finding.id,
                source_passage=finding.source_passage,
                fingerprint=fingerprint,
                attributes={"finding_type": finding.finding_type, "predicate": finding.predicate},
            ))
            counts["relationships_created"] += 1

        country_code = details.get("country_code")
        if country_code and relation_type != "located_in":
            country, country_action = upsert_entity(
                db, organization, name=country_code.upper(), entity_type="country", country_code=country_code.upper()
            )
            if country_action == "created_needs_review":
                counts["entities_created"] += 1
            location_fp = _fingerprint(
                str(organization.id), str(country.id), str(subject.id), str(finding.id), "located_in"
            )
            has_location = db.scalar(select(SupplyChainRelationship.id).where(
                SupplyChainRelationship.organization_id == organization.id,
                SupplyChainRelationship.fingerprint == location_fp,
            ))
            if not has_location:
                db.add(SupplyChainRelationship(
                    organization_id=organization.id,
                    source_entity_id=country.id,
                    target_entity_id=subject.id,
                    relationship_type="located_in",
                    country_code=country_code.upper(),
                    confidence=finding.model_confidence,
                    validation_status="passage_verified",
                    evidence_document_id=finding.evidence_document_id,
                    source_finding_id=finding.id,
                    source_passage=finding.source_passage,
                    fingerprint=location_fp,
                    attributes={"derived_from_country_field": True},
                ))
                counts["relationships_created"] += 1
    db.commit()
    return counts


def _relationship_adjacency(
    relationships: list[SupplyChainRelationship], direction: str, *, only_dependencies: bool = False,
    include_ownership: bool = True,
) -> dict[UUID, list[tuple[SupplyChainRelationship, UUID]]]:
    adjacency: dict[UUID, list[tuple[SupplyChainRelationship, UUID]]] = {}
    for edge in relationships:
        if only_dependencies and edge.relationship_type not in DEPENDENCY_EDGE_TYPES:
            continue
        if not include_ownership and edge.relationship_type == "owns":
            continue
        if direction in {"downstream", "both"}:
            adjacency.setdefault(edge.source_entity_id, []).append((edge, edge.target_entity_id))
        if direction in {"upstream", "both"}:
            adjacency.setdefault(edge.target_entity_id, []).append((edge, edge.source_entity_id))
    return adjacency


def traverse_graph(
    db: Session,
    organization: Organization,
    *,
    root_entity_id: UUID | None = None,
    direction: str = "both",
    max_depth: int = 4,
    country_code: str | None = None,
    include_ownership: bool = True,
) -> dict[str, Any]:
    if direction not in {"upstream", "downstream", "both"}:
        raise ValueError("direction must be upstream, downstream or both")
    if max_depth < 1 or max_depth > 8:
        raise ValueError("max_depth must be between 1 and 8")
    root = db.get(SupplyChainEntity, root_entity_id) if root_entity_id else ensure_root_entity(db, organization)
    if root is None or root.organization_id != organization.id:
        raise LookupError("Root entity not found in this organization's graph")
    db.flush()
    edges = list(db.scalars(select(SupplyChainRelationship).where(
        SupplyChainRelationship.organization_id == organization.id
    )).all())
    nodes_all = {row.id: row for row in db.scalars(select(SupplyChainEntity).where(
        SupplyChainEntity.organization_id == organization.id
    )).all()}
    adjacency = _relationship_adjacency(edges, direction, include_ownership=include_ownership)
    depths: dict[UUID, int] = {root.id: 0}
    paths: dict[UUID, list[UUID]] = {root.id: [root.id]}
    path_edges: dict[UUID, list[UUID]] = {root.id: []}
    traversed_edge_ids: set[UUID] = set()
    queue: deque[UUID] = deque([root.id])
    while queue:
        current = queue.popleft()
        depth = depths[current]
        if depth >= max_depth:
            continue
        for edge, neighbor in adjacency.get(current, []):
            traversed_edge_ids.add(edge.id)
            if neighbor in depths:
                continue
            depths[neighbor] = depth + 1
            paths[neighbor] = paths[current] + [neighbor]
            path_edges[neighbor] = path_edges[current] + [edge.id]
            queue.append(neighbor)
    if country_code:
        wanted = country_code.upper()
        keep = {entity_id for entity_id, entity in nodes_all.items() if entity_id in depths and entity.country_code == wanted}
        keep.add(root.id)
    else:
        keep = set(depths)
    kept_ids = keep
    output_nodes = [
        {"entity": nodes_all[entity_id], "depth": depths[entity_id], "path_entity_ids": paths[entity_id]}
        for entity_id in kept_ids if entity_id in nodes_all
    ]
    output_edges = [edge for edge in edges if edge.id in traversed_edge_ids and edge.source_entity_id in kept_ids and edge.target_entity_id in kept_ids]
    return {
        "organization_id": organization.id,
        "root_entity_id": root.id,
        "direction": direction,
        "max_depth": max_depth,
        "tier_definition": "The root is depth 0; each traversed relationship adds one tier. max_depth=4 includes paths through four edges.",
        "nodes": output_nodes,
        "relationships": output_edges,
    }


def calculate_downstream_impact(
    db: Session,
    organization: Organization,
    origin_entity_id: UUID,
    *,
    max_depth: int = 4,
    event_id: UUID | None = None,
) -> dict[str, Any]:
    if max_depth < 1 or max_depth > 8:
        raise ValueError("max_depth must be between 1 and 8")
    origin = db.get(SupplyChainEntity, origin_entity_id)
    if origin is None or origin.organization_id != organization.id:
        raise LookupError("Origin entity not found in this organization's graph")
    edges = list(db.scalars(select(SupplyChainRelationship).where(
        SupplyChainRelationship.organization_id == organization.id,
    )).all())
    nodes_all = {row.id: row for row in db.scalars(select(SupplyChainEntity).where(
        SupplyChainEntity.organization_id == organization.id
    )).all()}
    adjacency = _relationship_adjacency(edges, "downstream", only_dependencies=True)
    depths: dict[UUID, int] = {origin.id: 0}
    paths: dict[UUID, list[UUID]] = {origin.id: [origin.id]}
    edge_paths: dict[UUID, list[UUID]] = {origin.id: []}
    queue: deque[UUID] = deque([origin.id])
    while queue:
        current = queue.popleft()
        if depths[current] >= max_depth:
            continue
        for edge, neighbor in adjacency.get(current, []):
            if neighbor in depths:
                continue
            depths[neighbor] = depths[current] + 1
            paths[neighbor] = paths[current] + [neighbor]
            edge_paths[neighbor] = edge_paths[current] + [edge.id]
            queue.append(neighbor)
    impacted = []
    for entity_id, depth in depths.items():
        if entity_id == origin.id:
            continue
        entity = nodes_all.get(entity_id)
        if entity is None:
            continue
        impacted.append({
            "entity": entity,
            "depth": depth,
            "path_entity_ids": paths[entity_id],
            "path_relationship_ids": edge_paths[entity_id],
            "exposure_reason": "Reachable through source-linked downstream dependency relationships; this is graph exposure, not proof of realized impact.",
        })
    return {
        "organization_id": organization.id,
        "origin_entity_id": origin.id,
        "origin_entity_name": origin.name,
        "event_id": event_id,
        "max_depth": max_depth,
        "affected_entities": impacted,
        "notes": [
            "Exposure is calculated from stored relationship paths, not LLM-generated assumptions.",
            "The path indicates potential dependency exposure; actual impact requires separate confirmation.",
        ],
    }



def evidence_document_read(db: Session, organization_id: UUID, document_id: UUID) -> dict[str, Any] | None:
    document = _document_for_organization(db, organization_id, document_id)
    if document is None:
        return None
    passages = []
    for finding in db.scalars(select(InvestigationFinding).where(
        InvestigationFinding.organization_id == organization_id,
        InvestigationFinding.evidence_document_id == document.id,
    )).all():
        if finding.source_passage:
            passages.append({"record_type": "finding", "record_id": finding.id, "validation_status": finding.validation_status, "passage": finding.source_passage})
    for edge in db.scalars(select(SupplyChainRelationship).where(
        SupplyChainRelationship.organization_id == organization_id,
        SupplyChainRelationship.evidence_document_id == document.id,
    )).all():
        passages.append({"record_type": "relationship", "record_id": edge.id, "validation_status": edge.validation_status, "passage": edge.source_passage})
    for event in db.scalars(select(DisruptionEvent).where(
        DisruptionEvent.organization_id == organization_id,
        DisruptionEvent.evidence_document_id == document.id,
    )).all():
        passages.append({"record_type": "disruption_event", "record_id": event.id, "validation_status": event.validation_status, "passage": event.source_passage})
    return {
        "organization_id": organization_id,
        "document_id": document.id,
        "source_url": _source_url(db, document),
        "title": document.title,
        "content_hash": document.content_hash,
        "content_type": document.content_type,
        "published_at": document.published_at,
        "fetched_at": document.fetched_at,
        "is_truncated": document.is_truncated,
        "content_excerpt": document.content_text[:1200],
        "passages": passages,
    }
