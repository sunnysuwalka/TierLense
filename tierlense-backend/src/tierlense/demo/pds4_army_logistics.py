"""Deterministic PDS-4 demo dataset.

IMPORTANT: Every supplier, ownership record, relationship, disruption and evidence
excerpt created here is synthetic. This is a demonstration fixture inspired by the
high-level aims of the Indian Army CPDS 2025 PDS No. 4 (AI-based supply-chain
mapping); it is NOT a claim about real Indian Army procurement or suppliers.
No network or model-provider calls are made.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tierlense.models import (
    DiscoveredSource,
    DisruptionEvent,
    EvidenceChange,
    EvidenceDocument,
    InvestigationFinding,
    InvestigationJob,
    InvestigationSource,
    InvestigationSchedule,
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.schemas.operations import AlternativeSupplierRequest
from tierlense.schemas.supply_chain import DisruptionEventCreate, SupplyChainRelationshipCreate
from tierlense.services.disruption_assessment import assess_disruption_likelihood
from tierlense.services.operations import create_investigation_snapshot, recommend_alternatives
from tierlense.services.supply_chain import (
    create_disruption_event,
    create_relationship,
    ensure_root_entity,
    upsert_entity,
)

DEMO_ORGANIZATION_NAME = "PDS-4 Demo - Army Logistics Spares (SIMULATED)"
DEMO_SCENARIO_ID = "pds4_army_logistics_v1"
DEMO_DOMAIN = "pds4-demo.invalid"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _set_if_present(obj: Any, attr: str, value: Any) -> None:
    # Keeps the fixture compatible across the project's pre-metrics and post-metrics
    # InvestigationJob model versions without weakening any runtime validation.
    if hasattr(obj, attr):
        setattr(obj, attr, value)


def seed_pds4_army_logistics_demo(
    db: Session,
    organization: Organization,
    job: InvestigationJob,
) -> dict[str, Any]:
    """Seed one coherent simulated graph into the uncommitted onboarding transaction."""
    existing_root = db.scalar(select(SupplyChainEntity).where(
        SupplyChainEntity.organization_id == organization.id,
        SupplyChainEntity.is_root.is_(True),
    ))
    if existing_root and (existing_root.attributes or {}).get("demo_scenario_id") == DEMO_SCENARIO_ID:
        return (existing_root.attributes or {}).get("demo_seed_summary", {"already_seeded": True})

    now = _now()
    today = now.date().isoformat()
    organization.description = (
        "SIMULATED PDS-4 demonstration fixture for an Army logistics-vehicle preventive-maintenance "
        "spares supply chain. All supplier names, supply relationships, ownership percentages, board links, "
        "risk events and source excerpts are synthetic; this is not actual Indian Army procurement data."
    )
    organization.identity_status = "verified"  # The monitored root is the known demo fixture itself.

    root = ensure_root_entity(db, organization)
    root.attributes = {
        **(root.attributes or {}),
        "demo_scenario_id": DEMO_SCENARIO_ID,
        "data_status": "SIMULATED",
        "scenario_title": "Army logistics vehicle preventive-maintenance spares",
        "scenario_disclaimer": "Synthetic fixture only; no real procurement or supplier relationship is asserted.",
    }
    db.flush()

    # Entity descriptions are fictional and intentionally labelled SIMULATED.
    entity_specs = {
        "tier1_primary": ("Narmada Fleet Spares [SIMULATED]", "organization", "IN", "verified", "primary", "vehicle preventive maintenance spare kits"),
        "tier1_alternate": ("Kaveri Fleet Spares [SIMULATED]", "organization", "IN", "verified", "alternate", "vehicle preventive maintenance spare kits"),
        "tier2_filter": ("Deccan Filtration Systems [SIMULATED]", "organization", "IN", "verified", "primary", "air and oil filter assemblies"),
        "tier2_filter_alt": ("Bharat Industrial Filters [SIMULATED]", "organization", "IN", "needs_review", "alternate", "air and oil filter assemblies"),
        "tier2_seals": ("Triveni Elastomer Components [SIMULATED]", "organization", "IN", "needs_review", "primary", "gasket and O-ring sets"),
        "tier3_media": ("Sahyadri Filter Media [SIMULATED]", "organization", "IN", "needs_review", "primary", "filter media rolls"),
        "tier3_media_alt": ("Kaveri Filter Technologies [SIMULATED]", "organization", "IN", "verified", "alternate", "filter media rolls"),
        "tier3_elastomer": ("IndoSeal Compound Works [SIMULATED]", "organization", "IN", "needs_review", "primary", "NBR elastomer compound"),
        "tier4_polymer": ("Western Polymer Feedstock [SIMULATED]", "organization", "IN", "needs_review", "primary", "filter-grade polymer resin"),
        "tier4_resin": ("Shinano Specialty Resin [SIMULATED]", "organization", "JP", "needs_review", "primary", "filter-grade polymer resin"),
        "tier4_elastomer": ("Kansai Elastomer Feedstock [SIMULATED]", "organization", "JP", "needs_review", "primary", "elastomer base polymer"),
        "owner_major": ("Aarav Infrastructure Holdings [SIMULATED]", "organization", "IN", "needs_review", "shareholder", "industrial investment holding"),
        "owner_state": ("Public Industrial Participation Trust [SIMULATED]", "organization", "IN", "needs_review", "shareholder", "public-sector investment holding"),
        "owner_small1": ("Minority Holder Alpha 1.1% [SIMULATED]", "organization", "IN", "needs_review", "shareholder", "minority equity holding"),
        "owner_small2": ("Minority Holder Beta 0.8% [SIMULATED]", "organization", "IN", "needs_review", "shareholder", "minority equity holding"),
        "director1": ("Director A [SIMULATED]", "person", "IN", "needs_review", "board member", "board relationship"),
        "director2": ("Director B [SIMULATED]", "person", "IN", "needs_review", "board member", "board relationship"),
        "country_in": ("India", "country", "IN", "verified", "country", "country of origin"),
        "country_jp": ("Japan", "country", "JP", "verified", "country", "country of origin"),
    }
    entities: dict[str, SupplyChainEntity] = {"root": root}
    for key, (name, entity_type, country_code, identity_status, supplier_role, function) in entity_specs.items():
        entity, _action = upsert_entity(
            db,
            organization,
            name=name,
            entity_type=entity_type,
            country_code=country_code,
            aliases=[],
            attributes={
                "demo_scenario_id": DEMO_SCENARIO_ID,
                "data_status": "SIMULATED",
                "supplier_role": supplier_role,
                "recorded_function": function,
                "identity_basis": "Known identifier inside a synthetic demo fixture; not real-world identity verification.",
            },
        )
        entity.identity_status = identity_status
        entity.resolution_confidence = 1.0 if identity_status == "verified" else 0.55
        entity.attributes = {
            **(entity.attributes or {}),
            "demo_scenario_id": DEMO_SCENARIO_ID,
            "data_status": "SIMULATED",
            "supplier_role": supplier_role,
            "recorded_function": function,
            "identity_basis": "Known identifier inside a synthetic demo fixture; not real-world identity verification.",
        }
        entities[key] = entity
    db.flush()

    # Six synthetic source documents. The reserved .invalid domain prevents these
    # local fixture records from being mistaken for live public sources.
    doc_specs = {
        "tier1": {
            "slug": "tier1-procurement-summary",
            "title": "SIMULATED demo evidence — Tier 1 procurement and alternate vendor",
            "lines": [
                "SIMULATED SCENARIO: Narmada Fleet Spares [SIMULATED] supplies vehicle preventive maintenance spare kits to PDS-4 Demo - Army Logistics Spares (SIMULATED).",
                "SIMULATED SCENARIO: Kaveri Fleet Spares [SIMULATED] is an alternate supplier of vehicle preventive maintenance spare kits to PDS-4 Demo - Army Logistics Spares (SIMULATED).",
            ],
        },
        "tier2": {
            "slug": "tier2-component-suppliers",
            "title": "SIMULATED demo evidence — Tier 2 filtration and seal components",
            "lines": [
                "SIMULATED SCENARIO: Deccan Filtration Systems [SIMULATED] provides air and oil filter assemblies to Narmada Fleet Spares [SIMULATED].",
                "SIMULATED SCENARIO: Bharat Industrial Filters [SIMULATED] is an alternate supplier of air and oil filter assemblies to Narmada Fleet Spares [SIMULATED].",
                "SIMULATED SCENARIO: Triveni Elastomer Components [SIMULATED] provides gasket and O-ring sets to Narmada Fleet Spares [SIMULATED].",
            ],
        },
        "tier3": {
            "slug": "tier3-subcomponents",
            "title": "SIMULATED demo evidence — Tier 3 subcomponent suppliers",
            "lines": [
                "SIMULATED SCENARIO: Sahyadri Filter Media [SIMULATED] provides filter media rolls to Deccan Filtration Systems [SIMULATED].",
                "SIMULATED SCENARIO: Kaveri Filter Technologies [SIMULATED] is an alternate supplier of filter media rolls to Deccan Filtration Systems [SIMULATED].",
                "SIMULATED SCENARIO: IndoSeal Compound Works [SIMULATED] provides NBR elastomer compound to Triveni Elastomer Components [SIMULATED].",
            ],
        },
        "tier4": {
            "slug": "tier4-material-inputs",
            "title": "SIMULATED demo evidence — Tier 4 upstream material inputs",
            "lines": [
                "SIMULATED SCENARIO: Western Polymer Feedstock [SIMULATED] supplies filter-grade polymer resin to Sahyadri Filter Media [SIMULATED].",
                "SIMULATED SCENARIO: Shinano Specialty Resin [SIMULATED] supplies filter-grade polymer resin to Sahyadri Filter Media [SIMULATED].",
                "SIMULATED SCENARIO: Kansai Elastomer Feedstock [SIMULATED] supplies elastomer base polymer to IndoSeal Compound Works [SIMULATED].",
            ],
        },
        "governance": {
            "slug": "ownership-board-and-country-origin",
            "title": "SIMULATED demo evidence — Ownership, board links and origin",
            "lines": [
                "SIMULATED SCENARIO: Aarav Infrastructure Holdings [SIMULATED] holds 43.0 percent of Narmada Fleet Spares [SIMULATED].",
                "SIMULATED SCENARIO: Public Industrial Participation Trust [SIMULATED] holds 25.0 percent of Narmada Fleet Spares [SIMULATED] and is marked state-owned in this fixture.",
                "SIMULATED SCENARIO: Minority Holder Alpha 1.1% [SIMULATED] holds 1.1 percent of Narmada Fleet Spares [SIMULATED].",
                "SIMULATED SCENARIO: Minority Holder Beta 0.8% [SIMULATED] holds 0.8 percent of Narmada Fleet Spares [SIMULATED].",
                "SIMULATED SCENARIO: Director A [SIMULATED] has a board relationship with Narmada Fleet Spares [SIMULATED].",
                "SIMULATED SCENARIO: Director B [SIMULATED] has a board relationship with Deccan Filtration Systems [SIMULATED].",
                "SIMULATED SCENARIO: Narmada Fleet Spares [SIMULATED] is assigned country of origin India (IN) in this fixture.",
                "SIMULATED SCENARIO: Sahyadri Filter Media [SIMULATED] is assigned country of origin India (IN) in this fixture.",
                "SIMULATED SCENARIO: Shinano Specialty Resin [SIMULATED] is assigned country of origin Japan (JP) in this fixture.",
            ],
        },
        "disruptions": {
            "slug": "simulated-disruption-bulletin",
            "title": "SIMULATED demo evidence — Supply disruption scenario bulletin",
            "lines": [
                "SIMULATED SCENARIO: A 20-day filter-media line-maintenance window at Sahyadri Filter Media [SIMULATED] reduces available output; the downstream filter-assembly tier is exposed.",
                "SIMULATED SCENARIO: A 14-day inbound freight delay for Shinano Specialty Resin [SIMULATED] may constrain resin replenishment for the filter-media branch.",
                "SIMULATED SCENARIO: A temporary output constraint at IndoSeal Compound Works [SIMULATED] may delay NBR elastomer compound replenishment for gasket and O-ring sets.",
            ],
        },
    }
    docs: dict[str, dict[str, Any]] = {}
    for key, spec in doc_specs.items():
        content = "\n\n".join(spec["lines"])
        source_url = f"https://{DEMO_DOMAIN}/scenario/{spec['slug']}"
        source = db.scalar(select(DiscoveredSource).where(DiscoveredSource.canonical_url == source_url))
        if source is None:
            source = DiscoveredSource(
                canonical_url=source_url,
                source_domain=DEMO_DOMAIN,
                title=spec["title"],
                source_type="other",
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(source)
            db.flush()
        content_hash = _sha(content)
        document = db.scalar(select(EvidenceDocument).where(
            EvidenceDocument.source_id == source.id,
            EvidenceDocument.content_hash == content_hash,
        ))
        if document is None:
            document = EvidenceDocument(
                source_id=source.id,
                content_hash=content_hash,
                title=spec["title"],
                content_type="text/plain; charset=utf-8",
                content_text=content,
                content_length=len(content),
                http_status=None,
                published_at=now - timedelta(days=1),
                fetched_at=now,
                is_truncated=False,
                metadata_json={
                    "demo_scenario_id": DEMO_SCENARIO_ID,
                    "data_status": "SIMULATED",
                    "network_fetched": False,
                    "external_model_calls": 0,
                },
            )
            db.add(document)
            db.flush()
        source.latest_content_hash = content_hash
        source.latest_document_id = document.id
        source.last_seen_at = now
        link = db.scalar(select(InvestigationSource).where(
            InvestigationSource.job_id == job.id,
            InvestigationSource.source_id == source.id,
        ))
        if link is None:
            link = InvestigationSource(
                job_id=job.id,
                source_id=source.id,
                evidence_document_id=document.id,
                search_query="PDS-4 synthetic supply-chain demonstration fixture",
                discovery_snippet="Locally seeded synthetic evidence for a deterministic presentation scenario; not fetched from the internet.",
                relevant=True,
                relevance_score=1.0,
                relevance_reason="Included by deterministic demonstration fixture so every TierLense view has consistent test data.",
                relevance_categories=["pds4_demo", "supply_chain", "simulated"],
                fetch_status="processed",
                error_summary=None,
                discovered_at=now,
                updated_at=now,
            )
            db.add(link)
            db.flush()
        docs[key] = {"source": source, "document": document, "link": link, "content": content, "lines": spec["lines"]}

    # Create a prior bulletin version to make the source-change panel demonstrable.
    current_bulletin = docs["disruptions"]
    bulletin_source = current_bulletin["source"]
    previous_content = (
        "SIMULATED SCENARIO PREVIOUS VERSION: The supplier bulletin listed no current capacity signal. "
        "This is a generated fixture version, not a real-world notice."
    )
    previous_hash = _sha(previous_content)
    previous_document = db.scalar(select(EvidenceDocument).where(
        EvidenceDocument.source_id == bulletin_source.id,
        EvidenceDocument.content_hash == previous_hash,
    ))
    if previous_document is None:
        previous_document = EvidenceDocument(
            source_id=bulletin_source.id,
            content_hash=previous_hash,
            title="SIMULATED demo evidence — previous bulletin version",
            content_type="text/plain; charset=utf-8",
            content_text=previous_content,
            content_length=len(previous_content),
            http_status=None,
            published_at=now - timedelta(days=2),
            fetched_at=now - timedelta(days=1),
            is_truncated=False,
            metadata_json={"demo_scenario_id": DEMO_SCENARIO_ID, "data_status": "SIMULATED", "network_fetched": False},
        )
        db.add(previous_document)
        db.flush()

    # Findings are each tied to an exact passage in a locally stored synthetic document.
    def finding_for(doc_key: str, passage: str, finding_type: str, subject: str, predicate: str,
                    object_value: str | None = None, *, event_status: str = "reported",
                    details: dict[str, Any] | None = None, summary: str | None = None) -> InvestigationFinding:
        doc = docs[doc_key]
        fingerprint = _sha(f"{job.id}|{finding_type}|{passage.casefold()}")
        existing = db.scalar(select(InvestigationFinding).where(
            InvestigationFinding.job_id == job.id,
            InvestigationFinding.fingerprint == fingerprint,
        ))
        if existing:
            return existing
        row = InvestigationFinding(
            job_id=job.id,
            organization_id=organization.id,
            investigation_source_id=doc["link"].id,
            evidence_document_id=doc["document"].id,
            fingerprint=fingerprint,
            finding_type=finding_type,
            subject_name=subject,
            predicate=predicate,
            object_value=object_value,
            summary=summary or passage,
            event_status=event_status,
            event_date=today,
            source_passage=passage,
            model_confidence=0.99,
            validation_status="passage_verified",
            structured_details={
                "demo_scenario_id": DEMO_SCENARIO_ID,
                "data_status": "SIMULATED",
                "not_a_real_world_claim": True,
                **(details or {}),
            },
            created_at=now,
        )
        db.add(row)
        db.flush()
        return row

    relationship_count = 0

    def add_edge(doc_key: str, passage: str, source_key: str, target_key: str, relation_type: str,
                 component_or_service: str | None = None, *, ownership_percentage: float | None = None,
                 is_state_owned: bool | None = None, country_code: str | None = None,
                 finding_type: str = "supplier_relationship", predicate: str | None = None,
                 object_value: str | None = None) -> None:
        nonlocal relationship_count
        relation_predicate = predicate or relation_type
        finding = finding_for(
            doc_key, passage, finding_type, entities[source_key].name, relation_predicate,
            object_value or entities[target_key].name,
            details={
                "relationship_type": relation_type,
                "related_entity_name": entities[target_key].name,
                "related_entity_type": entities[target_key].entity_type,
                "component_or_service": component_or_service,
                "ownership_percentage": ownership_percentage,
                "is_state_owned": is_state_owned,
                "country_code": country_code,
            },
        )
        payload = SupplyChainRelationshipCreate(
            source_entity_id=entities[source_key].id,
            target_entity_id=entities[target_key].id,
            relationship_type=relation_type,
            evidence_document_id=docs[doc_key]["document"].id,
            source_finding_id=finding.id,
            source_passage=passage,
            component_or_service=component_or_service,
            ownership_percentage=ownership_percentage,
            is_state_owned=is_state_owned,
            country_code=country_code,
            as_of_date=today,
            confidence=0.99,
            attributes={"demo_scenario_id": DEMO_SCENARIO_ID, "data_status": "SIMULATED"},
        )
        edge, created = create_relationship(db, organization, payload)
        if created:
            relationship_count += 1

    # Tier 1: direct providers of the monitored maintenance-spares package.
    add_edge("tier1", doc_specs["tier1"]["lines"][0], "tier1_primary", "root", "supplies",
             "vehicle preventive maintenance spare kits", country_code="IN")
    add_edge("tier1", doc_specs["tier1"]["lines"][1], "tier1_alternate", "root", "supplies",
             "vehicle preventive maintenance spare kits", country_code="IN")

    # Tier 2: major serviceable assemblies supplied to the direct vendor.
    add_edge("tier2", doc_specs["tier2"]["lines"][0], "tier2_filter", "tier1_primary", "provides_component",
             "air and oil filter assemblies", country_code="IN")
    add_edge("tier2", doc_specs["tier2"]["lines"][1], "tier2_filter_alt", "tier1_primary", "provides_component",
             "air and oil filter assemblies", country_code="IN")
    add_edge("tier2", doc_specs["tier2"]["lines"][2], "tier2_seals", "tier1_primary", "provides_component",
             "gasket and O-ring sets", country_code="IN")

    # Tier 3: sub-components and processed materials.
    add_edge("tier3", doc_specs["tier3"]["lines"][0], "tier3_media", "tier2_filter", "provides_component",
             "filter media rolls", country_code="IN")
    add_edge("tier3", doc_specs["tier3"]["lines"][1], "tier3_media_alt", "tier2_filter", "provides_component",
             "filter media rolls", country_code="IN")
    add_edge("tier3", doc_specs["tier3"]["lines"][2], "tier3_elastomer", "tier2_seals", "provides_component",
             "NBR elastomer compound", country_code="IN")

    # Tier 4: upstream raw and specialty material inputs.
    add_edge("tier4", doc_specs["tier4"]["lines"][0], "tier4_polymer", "tier3_media", "supplies",
             "filter-grade polymer resin", country_code="IN")
    add_edge("tier4", doc_specs["tier4"]["lines"][1], "tier4_resin", "tier3_media", "supplies",
             "filter-grade polymer resin", country_code="JP")
    add_edge("tier4", doc_specs["tier4"]["lines"][2], "tier4_elastomer", "tier3_elastomer", "supplies",
             "elastomer base polymer", country_code="JP")

    # Ownership/board structure and country-of-origin links are synthetic, including
    # minority shareholdings below 1% to demonstrate the CPDS ownership lens.
    gov_lines = doc_specs["governance"]["lines"]
    add_edge("governance", gov_lines[0], "owner_major", "tier1_primary", "owns",
             ownership_percentage=43.0, is_state_owned=False, country_code="IN",
             finding_type="ownership_relationship")
    add_edge("governance", gov_lines[1], "owner_state", "tier1_primary", "owns",
             ownership_percentage=25.0, is_state_owned=True, country_code="IN",
             finding_type="ownership_relationship")
    add_edge("governance", gov_lines[2], "owner_small1", "tier1_primary", "owns",
             ownership_percentage=1.1, is_state_owned=False, country_code="IN",
             finding_type="ownership_relationship")
    add_edge("governance", gov_lines[3], "owner_small2", "tier1_primary", "owns",
             ownership_percentage=0.8, is_state_owned=False, country_code="IN",
             finding_type="ownership_relationship")
    add_edge("governance", gov_lines[4], "director1", "tier1_primary", "board_relationship",
             country_code="IN", finding_type="ownership_relationship")
    add_edge("governance", gov_lines[5], "director2", "tier2_filter", "board_relationship",
             country_code="IN", finding_type="ownership_relationship")
    add_edge("governance", gov_lines[6], "country_in", "tier1_primary", "located_in", country_code="IN",
             finding_type="technical_dependency")
    add_edge("governance", gov_lines[7], "country_in", "tier3_media", "located_in", country_code="IN",
             finding_type="technical_dependency")
    add_edge("governance", gov_lines[8], "country_jp", "tier4_resin", "located_in", country_code="JP",
             finding_type="technical_dependency")

    # A changed source URL version is included so evidence-change/history screens
    # have a real persisted record (but no actual network fetch happened).
    change = db.scalar(select(EvidenceChange).where(
        EvidenceChange.organization_id == organization.id,
        EvidenceChange.job_id == job.id,
        EvidenceChange.source_id == bulletin_source.id,
    ))
    if change is None:
        change = EvidenceChange(
            organization_id=organization.id,
            job_id=job.id,
            source_id=bulletin_source.id,
            previous_document_id=previous_document.id,
            current_document_id=current_bulletin["document"].id,
            previous_content_hash=previous_hash,
            current_content_hash=current_bulletin["document"].content_hash,
            change_type="content_changed",
            reassessment_status="completed",
            reassessment_details={
                "demo_scenario_id": DEMO_SCENARIO_ID,
                "data_status": "SIMULATED",
                "note": "Synthetic prior/current versions seeded for the presentation scenario; not detected from the internet.",
            },
            detected_at=now,
        )
        db.add(change)
        db.flush()

    # Three event types ensure disruption list, source passages and impact traversal
    # have concrete examples. They are scenario assumptions, not real-world incidents.
    disruption_specs = [
        ("tier3_media", doc_specs["disruptions"]["lines"][0], "capacity_shortage", "risk_signal", 4, "IN",
         "[SIMULATED SCENARIO] Filter-media line maintenance creates a 20-day capacity squeeze."),
        ("tier4_resin", doc_specs["disruptions"]["lines"][1], "logistics_disruption", "forecast", 3, "JP",
         "[SIMULATED SCENARIO] A 14-day resin freight delay may constrain replenishment."),
        ("tier3_elastomer", doc_specs["disruptions"]["lines"][2], "capacity_shortage", "risk_signal", 4, "IN",
         "[SIMULATED SCENARIO] An output constraint may delay elastomer-compound replenishment."),
    ]
    event_count = 0
    event_entities: list[SupplyChainEntity] = []
    for entity_key, passage, event_type, event_status, severity, country_code, summary in disruption_specs:
        event_finding = finding_for(
            "disruptions", passage, "disruption_event", entities[entity_key].name,
            event_type, summary, event_status=event_status,
            details={"disruption_type": event_type, "severity": severity, "country_code": country_code},
            summary=summary,
        )
        payload = DisruptionEventCreate(
            affected_entity_id=entities[entity_key].id,
            event_type=event_type,
            event_status=event_status,
            severity=severity,
            country_code=country_code,
            event_date=today,
            summary=summary,
            confidence=0.99,
            evidence_document_id=current_bulletin["document"].id,
            source_finding_id=event_finding.id,
            source_passage=passage,
        )
        event, created = create_disruption_event(db, organization, payload)
        if created:
            event_count += 1
        if event.affected_entity_id not in [item.id for item in event_entities]:
            event_entities.append(entities[entity_key])

    # Re-assessment results are explicitly the system's experimental, rule-based
    # index. Link assessment records to the synthetic source-change fixture.
    assessment_ids: list[str] = []
    for entity in event_entities:
        assessment = assess_disruption_likelihood(db, organization, entity.id)
        assessment.inputs = {
            **(assessment.inputs or {}),
            "trigger": "evidence_content_changed",
            "evidence_change_id": str(change.id),
            "demo_scenario_id": DEMO_SCENARIO_ID,
            "data_status": "SIMULATED",
        }
        assessment_ids.append(str(assessment.id))
    change.reassessment_status = "completed"
    change.reassessment_details = {
        **(change.reassessment_details or {}),
        "affected_entity_ids": [str(entity.id) for entity in event_entities],
        "assessment_ids": assessment_ids,
        "note": "Synthetic content-version change led to deterministic experimental reassessment; no model call or external fetch was made.",
    }

    # Populate persisted alternative-supplier history. The user can also run new
    # recommendations from the frontend; these precomputed rows are visible instantly.
    recommendation_count = 0
    root_alt = recommend_alternatives(
        db, organization, root.id,
        AlternativeSupplierRequest(required_function="vehicle preventive maintenance spare kits", limit=10),
    )
    recommendation_count += 1
    filter_alt = recommend_alternatives(
        db, organization, entities["tier2_filter"].id,
        AlternativeSupplierRequest(required_function="filter media rolls", limit=10),
    )
    recommendation_count += 1

    # Snapshot should include the graph, disruption events, risk assessments and the
    # source-change record created above.
    sources_count = len(docs)
    documents_count = len(docs)
    findings_count = int(db.scalar(select(func.count(InvestigationFinding.id)).where(
        InvestigationFinding.job_id == job.id,
    )) or 0)
    entity_count = int(db.scalar(select(func.count(SupplyChainEntity.id)).where(
        SupplyChainEntity.organization_id == organization.id,
    )) or 0)
    relation_total = int(db.scalar(select(func.count(SupplyChainRelationship.id)).where(
        SupplyChainRelationship.organization_id == organization.id,
    )) or 0)
    event_total = int(db.scalar(select(func.count(DisruptionEvent.id)).where(
        DisruptionEvent.organization_id == organization.id,
    )) or 0)
    change_total = int(db.scalar(select(func.count(EvidenceChange.id)).where(
        EvidenceChange.organization_id == organization.id,
    )) or 0)
    result_summary = {
        "sources_discovered": 0,
        "sources_relevant": 0,
        "documents_fetched": 0,
        "documents_reused": 0,
        "demo_sources_seeded_locally": sources_count,
        "demo_documents_seeded_locally": documents_count,
        "evidence_changes_detected": change_total,
        "findings_extracted": 0,
        "passages_verified": findings_count,
        "demo_findings_seeded_locally": findings_count,
        "unsupported_findings": 0,
        "needs_review_findings": 0,
        "entities_needing_identity_review": sum(1 for item in entities.values() if item.identity_status == "needs_review"),
        "identity_rejected_sources": 0,
        "fetch_failures": 0,
        "sources_skipped": 0,
        "graph_entities_created": max(entity_count - 1, 0),
        "graph_relationships_created": relation_total,
        "disruption_events_created": event_total,
        "risk_assessments_created_after_change": len(assessment_ids),
        "demo_scenario_id": DEMO_SCENARIO_ID,
        "data_status": "SIMULATED",
        "external_model_calls": 0,
        "external_provider_http_calls": 0,
        "message": "Synthetic PDS-4 demonstration scenario loaded locally. No external sources or model providers were called. Graph paths and risk signals are illustrative only; disruption index is experimental and uncalibrated.",
    }
    job.status = "completed"
    job.started_at = now
    job.finished_at = now
    job.attempt_count = 0  # The worker did not claim or execute this demonstration job.
    job.error_summary = None
    job.updated_at = now
    _set_if_present(job, "progress_percent", 100)
    _set_if_present(job, "progress_message", "Synthetic PDS-4 demonstration dataset prepared locally; no model calls.")
    _set_if_present(job, "result_summary", result_summary)
    _set_if_present(job, "execution_metrics", {
        "providers": {},
        "totals": {"requests": 0, "fallback_requests": 0, "successes": 0, "failures": 0,
                   "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "queue_attempt_count": 0,
        "demo_scenario_id": DEMO_SCENARIO_ID,
        "external_model_calls": 0,
    })
    _set_if_present(job, "next_attempt_at", None)
    _set_if_present(job, "lease_expires_at", None)
    _set_if_present(job, "worker_id", None)

    schedule = db.scalar(select(InvestigationSchedule).where(
        InvestigationSchedule.organization_id == organization.id,
    ))
    if schedule is not None:
        # The demo snapshot is completed locally, not enqueued to the worker.
        schedule.last_job_id = job.id
        schedule.last_enqueued_at = None
        schedule.last_success_at = now
        schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
        schedule.updated_at = now

    # Store the scenario counts on the root as a convenient UI/API discoverability hint.
    root.attributes = {
        **(root.attributes or {}),
        "demo_scenario_id": DEMO_SCENARIO_ID,
        "data_status": "SIMULATED",
        "scenario_title": "Army logistics vehicle preventive-maintenance spares",
        "scenario_disclaimer": "Synthetic fixture only; no real procurement or supplier relationship is asserted.",
        "demo_seed_summary": {
            "entities": entity_count,
            "relationships": relation_total,
            "evidence_documents": documents_count,
            "findings": findings_count,
            "disruption_events": event_total,
            "risk_assessments": len(assessment_ids),
            "alternative_supplier_recommendations": recommendation_count,
        },
    }
    db.flush()
    create_investigation_snapshot(db, job, now=now)
    db.flush()
    return {
        "organization_id": str(organization.id),
        "job_id": str(job.id),
        "data_status": "SIMULATED",
        "entities": entity_count,
        "relationships": relation_total,
        "evidence_documents": documents_count,
        "findings": findings_count,
        "disruption_events": event_total,
        "risk_assessments": len(assessment_ids),
        "alternative_supplier_recommendations": recommendation_count,
        "external_model_calls": 0,
    }
