"""Run a live Sprint 3 API acceptance scenario using clearly synthetic evidence.

This creates a separate test organization, writes one explicitly synthetic evidence
fixture into the local PostgreSQL database, then exercises the real graph APIs.
It does not run an LLM investigation or contact any external evidence URL.
Run from the TierLense project root with the API running and the worker stopped.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from uuid import uuid4, UUID

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tierlense.core.config import get_settings
from tierlense.models import DiscoveredSource, EvidenceDocument, InvestigationJob, InvestigationSource

API_ROOT = "http://127.0.0.1:8000"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6]
    org_name = f"SPRINT 3 SYNTHETIC ACCEPTANCE {run_tag} (NOT A REAL COMPANY)"
    print("TierLense Sprint 3 live acceptance scenario")
    print("IMPORTANT: This test data is synthetic and must not be presented as real-world supply-chain evidence.")
    print(f"API: {API_ROOT}")

    engine = create_engine(get_settings().database_url)
    client = httpx.Client(base_url=API_ROOT, timeout=30.0)

    def request(method: str, path: str, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} returned HTTP {response.status_code}: {response.text}")
        return response.json() if response.content else None

    try:
        ready = request("GET", "/api/v1/health/ready")
        print(f"API readiness: {ready}")

        onboard = request("POST", "/api/v1/organizations", json={
            "name": org_name,
            "country_code": "US",
            "description": "Synthetic Sprint 3 acceptance fixture. Not a real organization or supply chain.",
            "watch_profile": {
                "dependency_role": "synthetic acceptance test",
                "products_services": ["synthetic test fixture"],
                "dependency_context": "Test-only graph, disruption and impact validation. No real-world assertions.",
                "criticality": "low",
                "identity_clues": ["synthetic acceptance fixture", run_tag],
            },
        })
        org_id = onboard["organization"]["id"]
        job_id = onboard["initial_investigation"]["id"]
        print(f"Synthetic organization: {org_name}")
        print(f"Organization ID: {org_id}")

        supplier = f"TEST-{run_tag} Tier One Supplier"
        manufacturer = f"TEST-{run_tag} Tier Two Manufacturer"
        integrator = f"TEST-{run_tag} Tier Three Integrator"
        oem = f"TEST-{run_tag} Tier Four OEM"

        passage_1 = f"{supplier} supplies components to {manufacturer}."
        passage_2 = f"{manufacturer} supplies modules to {integrator}."
        passage_3 = f"{integrator} supplies assemblies to {oem}."
        passage_4 = f"{oem} supplies systems to {org_name}."
        passage_ownership = f"{supplier} owns 5 percent of {manufacturer}."
        passage_country = f"{manufacturer} operates a facility in China."
        passage_event = f"{supplier} reported a production shutdown that reduced output for downstream customers."
        evidence_text = "\n".join([
            "SYNTHETIC TEST FIXTURE ONLY. The following statements are invented solely to validate TierLense APIs.",
            passage_1, passage_2, passage_3, passage_4, passage_ownership, passage_country, passage_event,
        ])

        # Seed one fixture document attached to the onboarding job so the API can
        # enforce the same document ownership and exact-passage checks used in production.
        with Session(engine) as db:
            job = db.get(InvestigationJob, UUID(job_id))
            require(job is not None, "The onboarding investigation job was not found in the database.")
            # Mark the auto-created scan as intentionally not run, so restarting the
            # worker later will not spend model quota on this synthetic organization.
            job.status = "failed"
            job.finished_at = datetime.now(timezone.utc)
            job.error_summary = "Synthetic Sprint 3 acceptance fixture: automatic AI scan intentionally not run."
            if hasattr(job, "progress_message"):
                job.progress_message = "Synthetic fixture seeded; no AI investigation was executed."
            if hasattr(job, "next_attempt_at"):
                job.next_attempt_at = None
            if hasattr(job, "lease_expires_at"):
                job.lease_expires_at = None
            if hasattr(job, "worker_id"):
                job.worker_id = None

            source = DiscoveredSource(
                canonical_url=f"https://synthetic-evidence.invalid/{uuid4()}",
                source_domain="synthetic-evidence.invalid",
                title="SYNTHETIC TEST FIXTURE â€” NOT EXTERNAL EVIDENCE",
                source_type="synthetic_test_fixture",
            )
            db.add(source)
            db.flush()
            doc = EvidenceDocument(
                source_id=source.id,
                content_hash=hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
                title="SYNTHETIC TEST FIXTURE â€” NOT EXTERNAL EVIDENCE",
                content_type="text/plain",
                content_text=evidence_text,
                content_length=len(evidence_text),
                http_status=200,
                fetched_at=datetime.now(timezone.utc),
                is_truncated=False,
                metadata_json={"synthetic_fixture": True, "do_not_treat_as_external_fact": True, "run_tag": run_tag},
            )
            db.add(doc)
            db.flush()
            db.add(InvestigationSource(
                job_id=UUID(job_id),
                source_id=source.id,
                evidence_document_id=doc.id,
                relevant=True,
                relevance_score=1.0,
                relevance_reason="Synthetic acceptance fixture only; not a real-world claim.",
                relevance_categories=["synthetic_test_fixture"],
                fetch_status="processed",
            ))
            db.commit()
            doc_id = str(doc.id)
        print(f"Synthetic evidence document ID: {doc_id}")
        print("Auto-created AI scan marked as intentionally not run to avoid model usage.")

        prefix = f"/api/v1/supply-chain/organizations/{org_id}"
        # Materialize the monitored organization as the graph root.
        graph0 = request("GET", f"{prefix}/graph", params={"direction": "both", "max_depth": 4})
        root_id = graph0["root_entity_id"]

        def create_entity(name: str, country_code: str):
            result = request("POST", f"{prefix}/entities", json={
                "name": name, "entity_type": "organization", "country_code": country_code,
                "attributes": {"synthetic_test_fixture": True, "run_tag": run_tag},
            })
            return result["entity"]

        s1 = create_entity(supplier, "TW")
        s2 = create_entity(manufacturer, "CN")
        s3 = create_entity(integrator, "KR")
        s4 = create_entity(oem, "US")
        root_entity = request("GET", f"{prefix}/entities")
        root_item = next((x for x in root_entity["items"] if x["id"] == root_id), None)
        require(root_item is not None, "Could not find the monitored organization's root entity.")

        def create_edge(source, target, passage, **extra):
            result = request("POST", f"{prefix}/relationships", json={
                "source_entity_id": source["id"],
                "target_entity_id": target["id"],
                "relationship_type": "supplies",
                "evidence_document_id": doc_id,
                "source_passage": passage,
                "confidence": 0.9,
                "attributes": {"synthetic_test_fixture": True, "run_tag": run_tag},
                **extra,
            })
            require(result["relationship"]["validation_status"] == "passage_verified",
                    "Relationship was not marked passage_verified.")
            return result["relationship"]

        create_edge(s1, s2, passage_1, component_or_service="synthetic components")
        create_edge(s2, s3, passage_2, component_or_service="synthetic modules")
        create_edge(s3, s4, passage_3, component_or_service="synthetic assemblies")
        create_edge(s4, {"id": root_id, "name": org_name}, passage_4, component_or_service="synthetic systems")
        ownership = request("POST", f"{prefix}/relationships", json={
            "source_entity_id": s1["id"], "target_entity_id": s2["id"],
            "relationship_type": "owns", "ownership_percentage": 5.0,
            "evidence_document_id": doc_id, "source_passage": passage_ownership,
            "confidence": 0.9, "attributes": {"synthetic_test_fixture": True, "run_tag": run_tag},
        })
        require(ownership["relationship"]["ownership_percentage"] == 5.0,
                "Ownership percentage was not preserved.")

        china = request("POST", f"{prefix}/entities", json={
            "name": f"TEST-{run_tag} China", "entity_type": "country", "country_code": "CN",
            "attributes": {"synthetic_test_fixture": True, "run_tag": run_tag},
        })["entity"]
        request("POST", f"{prefix}/relationships", json={
            "source_entity_id": china["id"], "target_entity_id": s2["id"],
            "relationship_type": "located_in", "country_code": "CN",
            "evidence_document_id": doc_id, "source_passage": passage_country,
            "confidence": 0.9, "attributes": {"synthetic_test_fixture": True, "run_tag": run_tag},
        })

        graph = request("GET", f"{prefix}/graph", params={
            "root_entity_id": root_id, "direction": "upstream", "max_depth": 4,
        })
        supplier_node = next((n for n in graph["nodes"] if n["entity"]["id"] == s1["id"]), None)
        require(supplier_node is not None and supplier_node["depth"] == 4,
                "Four-edge upstream traversal did not reach the tier-one supplier at depth 4.")

        event_result = request("POST", f"{prefix}/disruptions", json={
            "affected_entity_id": s1["id"],
            "event_type": "production_shutdown",
            "event_status": "reported",
            "severity": 4,
            "country_code": "TW",
            "summary": "Synthetic test fixture: reported production shutdown at the tier-one supplier.",
            "evidence_document_id": doc_id,
            "source_passage": passage_event,
            "confidence": 0.9,
        })
        event = event_result["event"]
        require(event["validation_status"] == "passage_verified" and event["is_prediction"] is False,
                "Disruption event did not preserve source-validation status.")

        impact = request("GET", f"{prefix}/impact", params={
            "entity_id": s1["id"], "event_id": event["id"], "max_depth": 4,
        })
        affected_names = {item["entity"]["name"] for item in impact["affected_entities"]}
        expected = {manufacturer, integrator, oem, org_name}
        require(expected.issubset(affected_names),
                f"Downstream impact did not include expected four entities. Missing: {sorted(expected - affected_names)}")

        likelihood = request("GET", f"{prefix}/entities/{s1['id']}/likelihood")
        require(likelihood["is_experimental"] is True and likelihood["is_calibrated"] is False
                and likelihood["score_is_probability"] is False,
                "Likelihood endpoint did not declare experimental/un-calibrated/non-probability semantics.")
        evidence = request("GET", f"{prefix}/evidence/{doc_id}")
        require(evidence["content_excerpt"], "Evidence inspection returned no excerpt.")

        print("\n=== SPRINT 3 LIVE ACCEPTANCE PASSED ===")
        print(f"Organization ID: {org_id}")
        print(f"Evidence document ID: {doc_id}")
        print(f"Root entity ID: {root_id}")
        print(f"Disruption event ID: {event['id']}")
        print(f"Graph nodes returned: {len(graph['nodes'])}")
        print(f"Graph relationships returned: {len(graph['relationships'])}")
        print("Four-edge traversal: PASS")
        print("Passage-verified synthetic disruption: PASS")
        print("Downstream exposure through tier four to monitored organization: PASS")
        print("Country and ownership relationships: PASS")
        print("Experimental likelihood caveats: PASS")
        print("Evidence inspection: PASS")
        print("NOTE: This acceptance scenario uses explicitly synthetic data only; it is not real supply-chain intelligence.")
        return 0
    finally:
        client.close()
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nSPRINT 3 ACCEPTANCE FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)

