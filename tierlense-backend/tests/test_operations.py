"""Sprint 4 scheduling, change detection, history and alternative matching tests."""

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tierlense import models  # noqa: F401
from tierlense.db.base import Base
from tierlense.intelligence.pipeline import InvestigationPipeline
from tierlense.intelligence.schemas import FetchedDocument
from tierlense.models import (
    DiscoveredSource,
    EvidenceChange,
    EvidenceDocument,
    InvestigationJob,
    InvestigationSchedule,
    InvestigationSnapshot,
    InvestigationSource,
    Organization,
    SupplierRecommendation,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.services.job_queue import complete_job
from tierlense.services.operations import enqueue_due_scheduled_jobs


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, LocalSession


def test_due_schedule_enqueues_one_scheduled_scan_and_coalesces_missed_intervals():
    engine, factory = _factory()
    try:
        now = datetime.now(timezone.utc)
        with factory() as db:
            org = Organization(name="Scheduled Org", identity_status="unverified")
            db.add(org)
            db.flush()
            schedule = InvestigationSchedule(
                organization_id=org.id,
                enabled=True,
                interval_minutes=60,
                next_run_at=now - timedelta(minutes=5),
            )
            db.add(schedule)
            db.commit()
        first = enqueue_due_scheduled_jobs(factory, now=now)
        assert len(first) == 1
        with factory() as db:
            job = db.get(InvestigationJob, first[0])
            schedule = db.scalar(select(InvestigationSchedule))
            assert job.job_type == "scheduled_scan"
            assert job.status == "queued"
            assert schedule.last_job_id == job.id
            assert schedule.next_run_at.replace(tzinfo=timezone.utc) > now
        second = enqueue_due_scheduled_jobs(factory, now=now)
        assert second == []
    finally:
        engine.dispose()


def test_complete_job_persists_timestamped_snapshot_and_updates_schedule_success():
    engine, factory = _factory()
    try:
        now = datetime.now(timezone.utc)
        with factory() as db:
            org = Organization(name="History Org", identity_status="unverified")
            db.add(org)
            db.flush()
            job = InvestigationJob(
                organization_id=org.id, job_type="initial_scan", status="running",
                scheduled_at=now, attempt_count=1,
            )
            db.add(job)
            schedule = InvestigationSchedule(
                organization_id=org.id, enabled=True, interval_minutes=1440,
                next_run_at=now + timedelta(days=1),
            )
            db.add(schedule)
            db.flush()
            source = DiscoveredSource(canonical_url=f"https://example.org/{uuid4()}", source_domain="example.org", source_type="official")
            db.add(source)
            db.flush()
            doc = EvidenceDocument(
                source_id=source.id,
                content_hash=hashlib.sha256(b"historical evidence").hexdigest(),
                content_type="text/plain", content_text="historical evidence for snapshot",
                content_length=34, fetched_at=now, metadata_json={},
            )
            db.add(doc)
            db.flush()
            db.add(InvestigationSource(job_id=job.id, source_id=source.id, evidence_document_id=doc.id, fetch_status="processed"))
            db.commit()
            job_id = job.id
            org_id = org.id
            doc_id = doc.id
        complete_job(factory, job_id, result_summary={"sources_discovered": 1}, now=now)
        with factory() as db:
            snapshot = db.scalar(select(InvestigationSnapshot).where(InvestigationSnapshot.job_id == job_id))
            schedule = db.scalar(select(InvestigationSchedule).where(InvestigationSchedule.organization_id == org_id))
            assert snapshot is not None
            assert snapshot.snapshot_at.replace(tzinfo=timezone.utc) == now
            assert str(doc_id) in snapshot.evidence_document_ids
            assert snapshot.result_summary["sources_discovered"] == 1
            assert schedule.last_success_at.replace(tzinfo=timezone.utc) == now
    finally:
        engine.dispose()


def test_source_content_hash_change_creates_change_record():
    engine, factory = _factory()
    try:
        now = datetime.now(timezone.utc)
        with factory() as db:
            org = Organization(name="Changing Org", identity_status="unverified")
            db.add(org)
            db.flush()
            job = InvestigationJob(organization_id=org.id, job_type="scheduled_scan", status="running", scheduled_at=now)
            db.add(job)
            db.flush()
            source = DiscoveredSource(canonical_url=f"https://example.org/{uuid4()}", source_domain="example.org", source_type="official")
            db.add(source)
            db.flush()
            old_text = "Old evidence states the component capacity is fifty units."
            old_hash = hashlib.sha256(old_text.encode()).hexdigest()
            old_doc = EvidenceDocument(
                source_id=source.id, content_hash=old_hash, content_type="text/plain",
                content_text=old_text, content_length=len(old_text), fetched_at=now - timedelta(days=1), metadata_json={},
            )
            db.add(old_doc)
            db.flush()
            source.latest_content_hash = old_hash
            source.latest_document_id = old_doc.id
            association = InvestigationSource(job_id=job.id, source_id=source.id)
            db.add(association)
            db.commit()
            association_id = association.id
            job_id = job.id
        pipeline = InvestigationPipeline(factory, discovery=None, fetcher=None, analyzer=None)
        new_text = "Updated evidence states the component capacity is thirty units."
        new_doc = FetchedDocument(
            url="https://example.org/test", title="Changed evidence", content_type="text/plain",
            content_text=new_text, content_hash=hashlib.sha256(new_text.encode()).hexdigest(),
            fetched_at=now, http_status=200,
        )
        new_doc_id, reused = pipeline._persist_document(association_id, new_doc)
        assert reused is False
        with factory() as db:
            change = db.scalar(select(EvidenceChange).where(EvidenceChange.job_id == job_id))
            source = db.get(DiscoveredSource, db.get(EvidenceDocument, new_doc_id).source_id)
            assert change is not None
            assert change.change_type == "content_changed"
            assert change.previous_content_hash == old_hash
            assert change.current_content_hash == new_doc.content_hash
            assert change.reassessment_status == "pending"
            assert source.latest_document_id == new_doc_id
            assert source.latest_content_hash == new_doc.content_hash
    finally:
        engine.dispose()


def _client_org_document(client, name: str, content: str):
    from tierlense.api.deps import get_db
    from tierlense.main import app

    created = client.post("/api/v1/organizations", json={"name": name, "country_code": "US"})
    assert created.status_code == 201, created.text
    org_id = created.json()["organization"]["id"]
    job_id = created.json()["initial_investigation"]["id"]
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        source = DiscoveredSource(
            canonical_url=f"https://evidence.example/{uuid4()}",
            source_domain="evidence.example", title="Test source", source_type="official",
        )
        db.add(source)
        db.flush()
        doc = EvidenceDocument(
            source_id=source.id,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            title="Test source", content_type="text/plain", content_text=content,
            content_length=len(content), http_status=200,
            fetched_at=datetime.now(timezone.utc), metadata_json={},
        )
        db.add(doc)
        db.flush()
        db.add(InvestigationSource(
            job_id=UUID(job_id), source_id=source.id, evidence_document_id=doc.id,
            relevant=True, relevance_score=1.0, fetch_status="processed",
        ))
        db.commit()
        return org_id, job_id, str(doc.id)
    finally:
        generator.close()


def test_schedule_api_history_api_and_alternative_recommendation(client):
    from tierlense.api.deps import get_db
    from tierlense.main import app

    passage = "Candidate Supplier Alpha provides power modules to Schedule Test Org."
    org_id, job_id, doc_id = _client_org_document(client, "Schedule Test Org", passage)

    schedule_response = client.get(f"/api/v1/organizations/{org_id}/scan-schedule")
    assert schedule_response.status_code == 200, schedule_response.text
    assert schedule_response.json()["enabled"] is True
    changed_schedule = client.put(
        f"/api/v1/organizations/{org_id}/scan-schedule",
        json={"enabled": True, "interval_minutes": 45},
    )
    assert changed_schedule.status_code == 200, changed_schedule.text
    assert changed_schedule.json()["interval_minutes"] == 45
    invalid_schedule = client.put(
        f"/api/v1/organizations/{org_id}/scan-schedule",
        json={"enabled": True, "interval_minutes": 1},
    )
    assert invalid_schedule.status_code == 422

    graph = client.get(f"/api/v1/supply-chain/organizations/{org_id}/graph")
    root_id = graph.json()["root_entity_id"]
    candidate = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/entities",
        json={"name": "Candidate Supplier Alpha", "entity_type": "organization", "country_code": "US"},
    )
    assert candidate.status_code == 201, candidate.text
    edge = client.post(
        f"/api/v1/supply-chain/organizations/{org_id}/relationships",
        json={
            "source_entity_id": candidate.json()["entity"]["id"],
            "target_entity_id": root_id,
            "relationship_type": "provides_component",
            "component_or_service": "power modules",
            "evidence_document_id": doc_id,
            "source_passage": passage,
            "confidence": 0.8,
        },
    )
    assert edge.status_code == 201, edge.text
    rec = client.post(
        f"/api/v1/organizations/{org_id}/entities/{root_id}/alternative-suppliers",
        json={"required_function": "power modules", "required_role": "supplier"},
    )
    assert rec.status_code == 201, rec.text
    rec_body = rec.json()
    assert rec_body["result_status"] == "conditional_matches_only"
    assert len(rec_body["candidates"]) == 1
    assert rec_body["candidates"][0]["match_status"] == "conditional_match"
    assert rec_body["candidates"][0]["identity_status"] in {"unverified", "needs_review"}
    assert rec_body["candidates"][0]["evidence_document_id"] == doc_id
    historical_recs = client.get(f"/api/v1/organizations/{org_id}/alternative-supplier-recommendations")
    assert historical_recs.status_code == 200
    assert historical_recs.json()["total"] == 1

    # Exercise snapshot retrieval through the public API.
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        job = db.get(InvestigationJob, UUID(job_id))
        snapshot = InvestigationSnapshot(
            organization_id=UUID(org_id), job_id=UUID(job_id), snapshot_at=datetime.now(timezone.utc),
            job_type="initial_scan", result_summary={"test_snapshot": True},
            evidence_document_ids=[doc_id], finding_ids=[], graph_entity_ids=[root_id],
            graph_relationship_ids=[edge.json()["relationship"]["id"]], evidence_change_ids=[],
        )
        db.add(snapshot)
        db.commit()
        snapshot_id = str(snapshot.id)
    finally:
        generator.close()
    history = client.get(f"/api/v1/organizations/{org_id}/history")
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    history_item = client.get(f"/api/v1/organizations/{org_id}/history/{snapshot_id}")
    assert history_item.status_code == 200, history_item.text
    assert history_item.json()["result_summary"]["test_snapshot"] is True


def test_changed_evidence_reassesses_entities_linked_to_old_graph_evidence():
    from tierlense.models import DisruptionEvent
    from tierlense.services.operations import reassess_pending_evidence_changes

    engine, factory = _factory()
    try:
        now = datetime.now(timezone.utc)
        with factory() as db:
            org = Organization(name="Risk Reassessment Org", identity_status="unverified")
            db.add(org)
            db.flush()
            job = InvestigationJob(organization_id=org.id, job_type="scheduled_scan", status="running", scheduled_at=now)
            db.add(job)
            db.flush()
            source = DiscoveredSource(canonical_url=f"https://example.org/{uuid4()}", source_domain="example.org", source_type="official")
            db.add(source)
            db.flush()
            old_text = "Risk Reassessment Org reported a production shutdown affecting its customers."
            old_hash = hashlib.sha256(old_text.encode()).hexdigest()
            old_doc = EvidenceDocument(
                source_id=source.id, content_hash=old_hash, content_type="text/plain",
                content_text=old_text, content_length=len(old_text), fetched_at=now - timedelta(days=1), metadata_json={},
            )
            new_text = "Risk Reassessment Org reports a production restart and restored capacity for customers."
            new_doc = EvidenceDocument(
                source_id=source.id, content_hash=hashlib.sha256(new_text.encode()).hexdigest(),
                content_type="text/plain", content_text=new_text, content_length=len(new_text), fetched_at=now, metadata_json={},
            )
            db.add_all([old_doc, new_doc])
            db.flush()
            root = SupplyChainEntity(
                organization_id=org.id, name=org.name, normalized_name="risk reassessment org",
                entity_type="organization", identity_status="monitored_root", resolution_confidence=1.0,
                is_root=True, aliases=[], attributes={},
            )
            supplier = SupplyChainEntity(
                organization_id=org.id, name="Supplier Node", normalized_name="supplier node",
                entity_type="organization", identity_status="verified", resolution_confidence=1.0,
                is_root=False, aliases=[], attributes={},
            )
            db.add_all([root, supplier])
            db.flush()
            edge = SupplyChainRelationship(
                organization_id=org.id, source_entity_id=supplier.id, target_entity_id=root.id,
                relationship_type="supplies", component_or_service="modules", confidence=0.9,
                validation_status="passage_verified", evidence_document_id=old_doc.id,
                source_passage="Risk Reassessment Org reported a production shutdown affecting its customers.",
                fingerprint=hashlib.sha256(b"reassessment-edge").hexdigest(), attributes={},
            )
            event = DisruptionEvent(
                organization_id=org.id, affected_entity_id=root.id, event_type="production_shutdown",
                event_status="reported", severity=4, summary="Reported production shutdown",
                confidence=0.9, validation_status="passage_verified", evidence_document_id=old_doc.id,
                source_passage=old_text, fingerprint=hashlib.sha256(b"reassessment-event").hexdigest(),
                is_prediction=False,
            )
            change = EvidenceChange(
                organization_id=org.id, job_id=job.id, source_id=source.id,
                previous_document_id=old_doc.id, current_document_id=new_doc.id,
                previous_content_hash=old_hash, current_content_hash=new_doc.content_hash,
                change_type="content_changed", reassessment_status="pending", reassessment_details={}, detected_at=now,
            )
            db.add_all([edge, event, change])
            db.commit()
            org_id, job_id, change_id = org.id, job.id, change.id

        with factory() as db:
            ids = reassess_pending_evidence_changes(db, job_id)
            db.commit()
            change = db.get(EvidenceChange, change_id)
            assert change.reassessment_status == "completed"
            assert str(org_id) not in change.reassessment_details.get("affected_entity_ids", [])
            # Entity IDs, not organization IDs, are recorded in the affected list.
            assert change.reassessment_details["assessment_ids"] == [str(item) for item in ids]
            assert len(ids) >= 1
            assert change.reassessment_details["affected_entity_ids"]
            assessment = db.get(models.DisruptionLikelihoodAssessment, ids[0])
            assert assessment is not None
            assert assessment.is_experimental is True
            assert assessment.is_calibrated is False
            assert assessment.inputs["trigger"] == "evidence_content_changed"
            assert assessment.inputs["evidence_change_id"] == str(change_id)
    finally:
        engine.dispose()
