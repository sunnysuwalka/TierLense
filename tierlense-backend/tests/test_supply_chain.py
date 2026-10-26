"""Sprint 3 graph, provenance, exposure and experimental-index tests."""

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from tierlense import models  # noqa: F401
from tierlense.api.deps import get_db
from tierlense.main import app
from tierlense.models import (
    DiscoveredSource,
    EvidenceDocument,
    InvestigationFinding,
    InvestigationJob,
    InvestigationSource,
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.services.supply_chain import materialize_verified_findings


def _db_from_client_override():
    generator = app.dependency_overrides[get_db]()
    return next(generator), generator


def _make_org_and_document(client, name="Test Monitored Org"):
    response = client.post("/api/v1/organizations", json={"name": name, "country_code": "US"})
    assert response.status_code == 201, response.text
    payload = response.json()
    org_id = payload["organization"]["id"]
    job_id = payload["initial_investigation"]["id"]

    evidence_text = "\n".join([
        "Tier One Supplier supplies components to Tier Two Manufacturer.",
        "Tier Two Manufacturer supplies modules to Tier Three Integrator.",
        "Tier Three Integrator supplies assemblies to Tier Four OEM.",
        "Tier Four OEM supplies systems to Test Monitored Org.",
        "Tier One Supplier owns 5 percent of Tier Two Manufacturer.",
        "Tier Two Manufacturer operates a facility in China.",
        "Tier One Supplier reported a production shutdown that reduced output for its customers.",
        "Test Monitored Org announced the test scenario for system validation.",
    ])
    db, generator = _db_from_client_override()
    try:
        source = DiscoveredSource(
            canonical_url=f"https://evidence.example/{uuid4()}",
            source_domain="evidence.example",
            title="Evidence-backed test scenario",
            source_type="official",
        )
        db.add(source)
        db.flush()
        doc = EvidenceDocument(
            source_id=source.id,
            content_hash=hashlib.sha256(evidence_text.encode()).hexdigest(),
            title="Evidence-backed test scenario",
            content_type="text/html",
            content_text=evidence_text,
            content_length=len(evidence_text),
            http_status=200,
            fetched_at=datetime.now(timezone.utc),
            is_truncated=False,
            metadata_json={},
        )
        db.add(doc)
        db.flush()
        db.add(InvestigationSource(
            job_id=UUID(job_id),
            source_id=source.id,
            evidence_document_id=doc.id,
            relevant=True,
            relevance_score=1.0,
            relevance_reason="Synthetic fixture source, not external fact",
            relevance_categories=["supplier_relationship"],
            fetch_status="processed",
        ))
        db.commit()
        return org_id, job_id, str(doc.id), evidence_text
    finally:
        generator.close()


def _create_entity(client, org_id, name, entity_type="organization", country_code=None):
    response = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/entities",
        json={"name": name, "entity_type": entity_type, "country_code": country_code},
    )
    assert response.status_code == 201, response.text
    return response.json()["entity"]


def _create_edge(client, org_id, doc_id, source, target, relationship_type, passage, **extra):
    response = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/relationships",
        json={
            "source_entity_id": source["id"],
            "target_entity_id": target["id"],
            "relationship_type": relationship_type,
            "evidence_document_id": doc_id,
            "source_passage": passage,
            "confidence": 0.9,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["relationship"]


def test_four_tier_graph_disruption_impact_ownership_country_and_evidence(client):
    org_id, _job_id, doc_id, _evidence = _make_org_and_document(client)
    # Materialize the root from the organization registry before creating the chain.
    graph_response = client.get(f"/api/v1/supply-chain/organizations/{org_id}/graph?direction=both&max_depth=4")
    assert graph_response.status_code == 200, graph_response.text
    root = graph_response.json()["root_entity_id"]
    db, generator = _db_from_client_override()
    try:
        root_entity = db.get(SupplyChainEntity, UUID(root))
        assert root_entity is not None
        root_read = {
            "id": str(root_entity.id), "name": root_entity.name, "entity_type": root_entity.entity_type,
            "country_code": root_entity.country_code,
        }
    finally:
        generator.close()

    t1 = _create_entity(client, org_id, "Tier One Supplier", country_code="TW")
    t2 = _create_entity(client, org_id, "Tier Two Manufacturer", country_code="CN")
    t3 = _create_entity(client, org_id, "Tier Three Integrator", country_code="KR")
    t4 = _create_entity(client, org_id, "Tier Four OEM", country_code="US")
    tier_root = {"id": root, "name": root_read["name"], "entity_type": "organization"}

    _create_edge(client, org_id, doc_id, t1, t2, "supplies", "Tier One Supplier supplies components to Tier Two Manufacturer.", component_or_service="power modules")
    _create_edge(client, org_id, doc_id, t2, t3, "supplies", "Tier Two Manufacturer supplies modules to Tier Three Integrator.")
    _create_edge(client, org_id, doc_id, t3, t4, "supplies", "Tier Three Integrator supplies assemblies to Tier Four OEM.")
    _create_edge(client, org_id, doc_id, t4, tier_root, "supplies", "Tier Four OEM supplies systems to Test Monitored Org.")
    ownership = _create_edge(
        client, org_id, doc_id, t1, t2, "owns",
        "Tier One Supplier owns 5 percent of Tier Two Manufacturer.", ownership_percentage=5.0,
    )
    assert ownership["ownership_percentage"] == 5.0

    country = _create_entity(client, org_id, "China", entity_type="country", country_code="CN")
    _create_edge(client, org_id, doc_id, country, t2, "located_in", "Tier Two Manufacturer operates a facility in China.", country_code="CN")

    graph = client.get(f"/api/v1/supply-chain/organizations/{org_id}/graph?root_entity_id={root}&direction=upstream&max_depth=4")
    assert graph.status_code == 200, graph.text
    graph_data = graph.json()
    tier_nodes = [node for node in graph_data["nodes"] if node["depth"] <= 4]
    assert any(node["depth"] == 4 and node["entity"]["name"] == "Tier One Supplier" for node in tier_nodes)

    event_response = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/disruptions",
        json={
            "affected_entity_id": t1["id"],
            "event_type": "production_shutdown",
            "event_status": "reported",
            "severity": 4,
            "summary": "A reported production shutdown at Tier One Supplier.",
            "evidence_document_id": doc_id,
            "source_passage": "Tier One Supplier reported a production shutdown that reduced output for its customers.",
        },
    )
    assert event_response.status_code == 201, event_response.text
    event = event_response.json()["event"]
    assert event["validation_status"] == "passage_verified"
    assert event["is_prediction"] is False

    impact = client.get(
        f"/api/v1/supply-chain/organizations/{org_id}/impact",
        params={"entity_id": t1["id"], "event_id": event["id"], "max_depth": 4},
    )
    assert impact.status_code == 200, impact.text
    affected_names = {item["entity"]["name"] for item in impact.json()["affected_entities"]}
    assert {"Tier Two Manufacturer", "Tier Three Integrator", "Tier Four OEM", root_read["name"]} <= affected_names

    ownership_filter = client.get(
        f"/api/v1/supply-chain/organizations/{org_id}/relationships",
        params={"relationship_type": "owns", "min_ownership_percentage": 1},
    )
    assert ownership_filter.status_code == 200
    assert len(ownership_filter.json()["items"]) == 1

    evidence = client.get(f"/api/v1/supply-chain/organizations/{org_id}/evidence/{doc_id}")
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["source_url"].startswith("https://evidence.example/")
    assert evidence.json()["content_excerpt"]

    likelihood = client.get(f"/api/v1/supply-chain/organizations/{org_id}/entities/{t1['id']}/likelihood")
    assert likelihood.status_code == 200, likelihood.text
    assert likelihood.json()["is_experimental"] is True
    assert likelihood.json()["is_calibrated"] is False
    assert likelihood.json()["score_is_probability"] is False


def test_relationship_rejects_passage_not_in_document(client):
    org_id, _job_id, doc_id, _evidence = _make_org_and_document(client, name="Evidence Test Org")
    t1 = _create_entity(client, org_id, "Supplier A")
    t2 = _create_entity(client, org_id, "Buyer B")
    response = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/relationships",
        json={
            "source_entity_id": t1["id"], "target_entity_id": t2["id"],
            "relationship_type": "supplies", "evidence_document_id": doc_id,
            "source_passage": "This fabricated supplier quote does not appear in the evidence.",
        },
    )
    assert response.status_code == 422
    assert "exact passage" in response.json()["detail"]


def test_exact_alias_resolution_reuses_entity_without_fuzzy_merge(client):
    org_id, _job_id, _doc_id, _evidence = _make_org_and_document(client, name="Entity Resolution Org")
    first = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/entities",
        json={"name": "Acme Industrial Ltd", "entity_type": "organization", "aliases": ["Acme Industrial"]},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/entities",
        json={"name": "Acme Industrial", "entity_type": "organization"},
    )
    assert second.status_code == 201
    assert second.json()["resolution_action"] == "matched_exact"
    assert first.json()["entity"]["id"] == second.json()["entity"]["id"]

    similar = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/entities",
        json={"name": "Acme Industriel", "entity_type": "organization"},
    )
    assert similar.status_code == 201
    assert similar.json()["entity"]["id"] != first.json()["entity"]["id"]
    assert similar.json()["entity"]["identity_status"] == "needs_review"


def test_verified_relationship_finding_materializes_idempotently(client):
    org_id, job_id, doc_id, _evidence = _make_org_and_document(client, name="Graph Materialization Org")
    db, generator = _db_from_client_override()
    try:
        org = db.get(Organization, UUID(org_id))
        association = db.scalar(select(InvestigationSource).where(InvestigationSource.job_id == UUID(job_id)))
        passage = "Test Monitored Org supplies modules to Example Foundry under a public agreement."
        doc = db.get(EvidenceDocument, UUID(doc_id))
        doc.content_text += "\n" + passage
        doc.content_length = len(doc.content_text)
        db.flush()
        finding = InvestigationFinding(
            job_id=UUID(job_id),
            organization_id=UUID(org_id),
            investigation_source_id=association.id,
            evidence_document_id=UUID(doc_id),
            fingerprint=hashlib.sha256(b"finding-materialization").hexdigest(),
            finding_type="supplier_relationship",
            subject_name="Graph Materialization Org",
            predicate="supplies",
            object_value="Example Foundry",
            summary="The organization supplies modules to Example Foundry.",
            event_status="reported",
            event_date=None,
            source_passage=passage,
            model_confidence=0.85,
            validation_status="passage_verified",
            structured_details={
                "related_entity_name": "Example Foundry",
                "related_entity_type": "organization",
                "relationship_type": "supplies",
                "component_or_service": "modules",
            },
        )
        db.add(finding)
        db.commit()
        first = materialize_verified_findings(db, UUID(job_id))
        second = materialize_verified_findings(db, UUID(job_id))
        assert first["relationships_created"] == 1
        assert second["relationships_created"] == 0
        edges = list(db.scalars(select(SupplyChainRelationship).where(
            SupplyChainRelationship.organization_id == UUID(org_id),
            SupplyChainRelationship.source_finding_id == finding.id,
        )).all())
        assert len(edges) == 1
        assert edges[0].validation_status == "passage_verified"
    finally:
        generator.close()


def test_source_linked_disruption_finding_materializes_event_and_is_idempotent(client):
    org_id, job_id, doc_id, _evidence = _make_org_and_document(client, name="Disruption Materialization Org")
    db, generator = _db_from_client_override()
    try:
        association = db.scalar(select(InvestigationSource).where(InvestigationSource.job_id == UUID(job_id)))
        doc = db.get(EvidenceDocument, UUID(doc_id))
        passage = "Test Monitored Org announced the test scenario for system validation."
        finding = InvestigationFinding(
            job_id=UUID(job_id),
            organization_id=UUID(org_id),
            investigation_source_id=association.id,
            evidence_document_id=UUID(doc_id),
            fingerprint=hashlib.sha256(b"disruption-materialization").hexdigest(),
            finding_type="disruption_event",
            subject_name="Disruption Materialization Org",
            predicate="reported production outage",
            object_value="Production system",
            summary="A source-linked disruption signal for the monitored organization.",
            event_status="risk_signal",
            event_date=None,
            source_passage=passage,
            model_confidence=0.8,
            validation_status="passage_verified",
            structured_details={"disruption_type": "operational_outage", "severity": 3, "country_code": "US"},
        )
        db.add(finding)
        db.commit()
        first = materialize_verified_findings(db, UUID(job_id))
        second = materialize_verified_findings(db, UUID(job_id))
        assert first["events_created"] == 1
        assert second["events_created"] == 0
    finally:
        generator.close()


def test_likelihood_without_verified_events_reports_insufficient_evidence(client):
    org_id, _job_id, _doc_id, _evidence = _make_org_and_document(client, name="No Signal Org")
    root_graph = client.get(f"/api/v1/supply-chain/organizations/{org_id}/graph")
    assert root_graph.status_code == 200
    root_id = root_graph.json()["root_entity_id"]
    response = client.get(f"/api/v1/supply-chain/organizations/{org_id}/entities/{root_id}/likelihood")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["band"] == "insufficient_evidence"
    assert payload["experimental_index"] == 0.0
    assert payload["score_is_probability"] is False
    assert payload["is_calibrated"] is False
