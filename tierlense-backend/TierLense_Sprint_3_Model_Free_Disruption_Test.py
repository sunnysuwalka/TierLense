"""Model-free, source-backed NVIDIA regulatory disruption acceptance test.

By default this script runs in a rollback-only dry run. Pass --apply to persist
an explicitly labelled manual evidence import, event, relationship, and assessment.
It does not make HTTP requests or call an LLM/model provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, desc, select
from sqlalchemy.orm import Session

from tierlense.core.config import get_settings
from tierlense.models import (
    DiscoveredSource,
    DisruptionEvent,
    DisruptionLikelihoodAssessment,
    EvidenceDocument,
    InvestigationJob,
    InvestigationSource,
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
)
from tierlense.schemas.supply_chain import DisruptionEventCreate, SupplyChainRelationshipCreate
from tierlense.services.disruption_assessment import assess_disruption_likelihood
from tierlense.services.supply_chain import (
    calculate_downstream_impact,
    create_disruption_event,
    create_relationship,
    normalize_entity_name,
    passage_is_in_document,
    upsert_entity,
)

ORGANIZATION_ID = UUID("6b1162ef-de63-4094-a6a9-cbf887e52f32")
ROOT_ENTITY_ID = UUID("a836f1b0-0200-4ba7-aef6-0742d5729c07")
SEC_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
SEC_TITLE = "NVIDIA Corporation Form 10-Q for quarter ended July 26, 2026"
IMPORT_JOB_ID = uuid5(NAMESPACE_URL, f"tierlense:manual-evidence-import:{ORGANIZATION_ID}:{SEC_URL}")

EVENT_PASSAGE = (
    "The U.S. government, or USG, granted licenses that would allow us to ship small amounts of H200 products "
    "to specific China-based customers, but such sales were restricted by the PRC government, and we have been "
    "unable to sell all the products for which we have licenses. During the first half of fiscal year 2027, we "
    "incurred a $0.4 billion charge associated with H200 for excess inventory and purchase obligations, as the "
    "demand for H200 products diminished."
)
MARKET_PASSAGE = (
    "As of the end of the second quarter of fiscal year 2027, while we were able to ship uncontrolled products "
    "to China, such as gaming and workstation GPUs, we were effectively foreclosed from competing in China’s "
    "data center computing/compute market, and our effective foreclosure from the China market helped our "
    "competitors build larger developer and customer ecosystems to challenge us worldwide."
)
CONTENT_TEXT = "\n\n".join(
    [
        "Selected excerpts from NVIDIA Corporation's official Form 10-Q for the quarter ended July 26, 2026. "
        "This is a manually curated excerpt, not the full filing; no automated retrieval or model inference was used.",
        (
            "In April 2025, the USG informed us that it requires a license for export to China (including Hong Kong "
            "and Macau) and D:5 countries, or to companies headquartered or with an ultimate parent therein, of our "
            "H20 integrated circuits and any other circuits achieving the H20’s memory bandwidth, interconnect "
            "bandwidth, or combination thereof."
        ),
        (
            "As a result of these requirements, we incurred a $4.5 billion charge in the first quarter of fiscal "
            "year 2026 associated with H20 for excess inventory and purchase obligations, as the demand for H20 "
            "products diminished."
        ),
        (
            "Beginning in August 2025, the USG granted licenses that would have allowed us to ship certain H20 "
            "products to certain China-based customers, but such sales were restricted by the PRC government, and "
            "we were unable to sell our H20 inventory."
        ),
        EVENT_PASSAGE,
        (
            "After incurring that charge, we have made a fraction of the allowed shipments under the USG’s H200 "
            "licensing program. Those shipments account for less than 1% of Data Center revenue in our most recent "
            "quarter. The licenses require that the H200s go through an inspection process in the United States "
            "prior to any shipment to the customer. As a result, any H200s shipped under the new licensing program "
            "are subject to a 25% tariff upon importation into the United States."
        ),
        (
            "The export controls applicable to China are complex and address a variety of parameters, including the "
            "total processing performance of a chip, the “performance density” of a chip, the interconnect bandwidth "
            "of a chip, and the memory bandwidth of a chip. Under the current rules and geopolitical landscape, we "
            "are unable to create and deliver a competitive product for wide distribution in China’s data center "
            "market with the approval from both the USG and the Chinese government."
        ),
        MARKET_PASSAGE,
        (
            "Unless we are able to return with a data center system that meets the approval of both the USG and the "
            "Chinese government, our lost opportunity and the benefit to our competitors will have a material and "
            "adverse impact on our business, operating results, and financial condition."
        ),
    ]
)

PRODUCT_ENTITY_NAME = "NVIDIA H20/H200 export-controlled product line"
MARKET_ENTITY_NAME = "China data-center computing market"


def ensure_manual_evidence(db: Session, organization: Organization) -> EvidenceDocument:
    source = db.scalar(select(DiscoveredSource).where(DiscoveredSource.canonical_url == SEC_URL))
    if source is None:
        source = DiscoveredSource(
            canonical_url=SEC_URL,
            source_domain=urlparse(SEC_URL).hostname or "www.sec.gov",
            title=SEC_TITLE,
            source_type="regulatory_filing",
        )
        db.add(source)
        db.flush()

    content_hash = hashlib.sha256(CONTENT_TEXT.encode("utf-8")).hexdigest()
    document = db.scalar(
        select(EvidenceDocument).where(
            EvidenceDocument.source_id == source.id,
            EvidenceDocument.content_hash == content_hash,
        )
    )
    if document is None:
        document = EvidenceDocument(
            source_id=source.id,
            content_hash=content_hash,
            title=SEC_TITLE,
            content_type="text/plain; charset=utf-8",
            content_text=CONTENT_TEXT,
            content_length=len(CONTENT_TEXT),
            http_status=None,  # TierLense itself did not issue an HTTP fetch.
            published_at=None,  # Keep publication timestamp unset rather than infer it.
            is_truncated=True,
            metadata_json={
                "manual_evidence_import": True,
                "manual_reviewed_source": True,
                "full_document_imported": False,
                "tierlense_http_fetch_performed": False,
                "external_model_inference_performed": False,
                "source_period_end": "2026-07-26",
                "source_sections": ["export controls and H20/H200 sales restrictions"],
                "source_note": "Selected excerpts copied from the official SEC filing for model-free acceptance testing.",
            },
        )
        db.add(document)
        db.flush()

    job = db.get(InvestigationJob, IMPORT_JOB_ID)
    now = datetime.now(timezone.utc)
    if job is None:
        job = InvestigationJob(
            id=IMPORT_JOB_ID,
            organization_id=organization.id,
            job_type="manual_scan",  # API-supported type; result_summary clearly labels it as manual import only.
            status="completed",
            scheduled_at=now,
            started_at=now,
            finished_at=now,
            attempt_count=0,
            progress_percent=100,
            progress_message="Manual evidence import only; no AI, discovery, or automated TierLense fetch was run.",
            result_summary={
                "mode": "manual_evidence_import_only",
                "sources_imported": 1,
                "automated_discovery": False,
                "automated_fetch": False,
                "model_inference": False,
                "external_model_calls": 0,
            },
            execution_metrics={
                "mode": "manual_evidence_import_only",
                "external_model_calls": 0,
                "provider_requests": 0,
                "automated_source_discovery": False,
                "automated_document_fetch": False,
            },
        )
        db.add(job)
        db.flush()

    link = db.scalar(
        select(InvestigationSource).where(
            InvestigationSource.job_id == job.id,
            InvestigationSource.source_id == source.id,
        )
    )
    if link is None:
        link = InvestigationSource(
            id=uuid5(NAMESPACE_URL, f"tierlense:manual-evidence-link:{job.id}:{source.id}"),
            job_id=job.id,
            source_id=source.id,
            evidence_document_id=document.id,
            search_query="Manual official SEC filing import; no automated discovery or model classification.",
            discovery_snippet=EVENT_PASSAGE,
            relevant=True,
            relevance_score=None,
            relevance_reason="Manually reviewed official SEC filing excerpt. No model classification was performed.",
            relevance_categories=["regulatory_action", "export_controls", "market_access"],
            fetch_status="manual_imported",
        )
        db.add(link)
    else:
        link.evidence_document_id = document.id
        link.fetch_status = "manual_imported"
        link.relevance_reason = "Manually reviewed official SEC filing excerpt. No model classification was performed."

    job.result_summary = {
        **(job.result_summary or {}),
        "manual_evidence_import": True,
        "evidence_document_id": str(document.id),
        "source_url": SEC_URL,
        "external_model_calls": 0,
    }
    job.execution_metrics = {
        **(job.execution_metrics or {}),
        "manual_evidence_import": True,
        "evidence_document_id": str(document.id),
        "external_model_calls": 0,
    }
    db.flush()
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the manual evidence/event/graph import; default is rollback-only dry run.")
    args = parser.parse_args()

    engine = create_engine(get_settings().database_url)
    result_summary: dict = {}
    try:
        with Session(engine) as db:
            organization = db.get(Organization, ORGANIZATION_ID)
            if organization is None:
                raise RuntimeError(f"NVIDIA monitored organization not found: {ORGANIZATION_ID}")
            root = db.get(SupplyChainEntity, ROOT_ENTITY_ID)
            if root is None or root.organization_id != organization.id or not root.is_root:
                raise RuntimeError("Expected canonical NVIDIA graph root was not found; no changes will be made.")
            if root.name != "NVIDIA Corporation":
                raise RuntimeError(f"Expected canonical root name; found {root.name!r}.")

            # Preflight validates the copied passages before any graph mutation.
            if EVENT_PASSAGE not in CONTENT_TEXT or MARKET_PASSAGE not in CONTENT_TEXT:
                raise RuntimeError("Selected SEC passages are not present in the proposed evidence excerpt.")

            document = ensure_manual_evidence(db, organization)
            source = db.get(DiscoveredSource, document.source_id)
            if not source or source.canonical_url != SEC_URL or (urlparse(source.canonical_url).hostname or "") != "www.sec.gov":
                raise RuntimeError("SEC source provenance check failed.")
            if not passage_is_in_document(EVENT_PASSAGE, document.content_text):
                raise RuntimeError("Disruption event passage does not match the captured SEC excerpt.")
            if not passage_is_in_document(MARKET_PASSAGE, document.content_text):
                raise RuntimeError("Market exposure passage does not match the captured SEC excerpt.")

            product, product_action = upsert_entity(
                db,
                organization,
                name=PRODUCT_ENTITY_NAME,
                entity_type="component",
                aliases=["H20 integrated circuits", "H200 products", "H20/H200 data-center GPUs"],
                attributes={
                    "entity_scope": "product_line",
                    "owner_entity_id": str(root.id),
                    "owner_entity_name": "NVIDIA Corporation",
                    "identity_basis": "Manually reviewed official NVIDIA SEC filing explicitly names H20 and H200 products.",
                    "model_inference_used": False,
                },
            )
            market, market_action = upsert_entity(
                db,
                organization,
                name=MARKET_ENTITY_NAME,
                entity_type="other",
                country_code="CN",
                attributes={
                    "entity_scope": "geographic_market_segment",
                    "market_name": "China data-center computing market",
                    "not_a_legal_entity": True,
                    "model_inference_used": False,
                },
            )
            db.flush()

            relationship_payload = SupplyChainRelationshipCreate(
                source_entity_id=product.id,
                target_entity_id=market.id,
                relationship_type="distributes_to",
                evidence_document_id=document.id,
                source_passage=MARKET_PASSAGE,
                component_or_service="Restricted H20/H200 export-controlled GPU sales into the China data-center market",
                country_code="CN",
                as_of_date="2026-07-26",
                confidence=0.7,
                attributes={
                    "relationship_scope": "market_access_exposure",
                    "sales_access_status": "restricted_and_limited",
                    "not_a_claim_of_unrestricted_or_normal_distribution": True,
                    "source_is_official_sec_filing": True,
                    "manually_reviewed": True,
                    "model_inference_used": False,
                    "confidence_is_calibrated_probability": False,
                },
            )
            relationship, relationship_created = create_relationship(db, organization, relationship_payload)

            event_payload = DisruptionEventCreate(
                affected_entity_id=product.id,
                event_type="regulatory_action",
                event_status="reported",
                severity=None,
                country_code="CN",
                event_date="2026-07-26",
                summary=(
                    "NVIDIA's official Form 10-Q for the quarter ended July 26, 2026 reports that U.S. export-licensing "
                    "requirements and PRC government restrictions prevented the company from selling all H200 products "
                    "licensed for China-based customers. The filing reports a $0.4 billion H200 excess-inventory and "
                    "purchase-obligation charge during the first half of fiscal 2027. This is a source-reported "
                    "regulatory/market-access disruption, not a claim of a physical factory shutdown. Severity is not assessed."
                ),
                confidence=0.5,
                evidence_document_id=document.id,
                source_passage=EVENT_PASSAGE,
            )
            event, event_created = create_disruption_event(db, organization, event_payload)

            impact = calculate_downstream_impact(
                db, organization, product.id, max_depth=4, event_id=event.id
            )
            affected_names = [item["entity"].name for item in impact["affected_entities"]]
            if MARKET_ENTITY_NAME not in affected_names:
                raise RuntimeError("The impact calculation did not include the source-supported China market exposure.")
            if any(name == "FCA Supercharged Sandbox" for name in affected_names):
                raise RuntimeError("Unrelated FCA service was returned as exposed to the H200 China market event.")

            existing_assessments = list(
                db.scalars(
                    select(DisruptionLikelihoodAssessment)
                    .where(
                        DisruptionLikelihoodAssessment.organization_id == organization.id,
                        DisruptionLikelihoodAssessment.entity_id == product.id,
                        DisruptionLikelihoodAssessment.model_version == "experimental-rules-v1",
                    )
                    .order_by(desc(DisruptionLikelihoodAssessment.assessed_at))
                    .limit(20)
                ).all()
            )
            expected_inputs = {
                "verified_event_count": 1,
                "downstream_dependency_edges": 1,
                "evidence_available": True,
            }
            assessment = next(
                (row for row in existing_assessments if (row.inputs or {}) == expected_inputs),
                None,
            )
            assessment_created = False
            if assessment is None:
                assessment = assess_disruption_likelihood(db, organization, product.id)
                assessment_created = True

            db.flush()
            result_summary = {
                "mode": "apply" if args.apply else "dry_run_rollback",
                "source_url": SEC_URL,
                "evidence_document_id": str(document.id),
                "manual_import_job_id": str(IMPORT_JOB_ID),
                "nvidia_root_entity_id": str(root.id),
                "product_entity_id": str(product.id),
                "product_entity_action": product_action,
                "market_entity_id": str(market.id),
                "market_entity_action": market_action,
                "relationship_id": str(relationship.id),
                "relationship_created": relationship_created,
                "relationship_validation": relationship.validation_status,
                "event_id": str(event.id),
                "event_created": event_created,
                "event_validation": event.validation_status,
                "impact_origin": product.name,
                "affected_entities": affected_names,
                "likelihood_assessment_id": str(assessment.id),
                "likelihood_index": assessment.experimental_index,
                "likelihood_band": assessment.band,
                "likelihood_is_calibrated": assessment.is_calibrated,
                "external_model_calls": 0,
                "external_provider_http_calls": 0,
            }

            if not args.apply:
                db.rollback()
                print(json.dumps(result_summary, indent=2, ensure_ascii=False))
                print("\nDRY RUN ONLY: all database changes were rolled back. No model/provider calls were made.")
                print("Review output, then rerun with --apply to persist.")
                return 0

            db.commit()

        # Post-commit verification from a new DB session.
        with Session(engine) as verify_db:
            org = verify_db.get(Organization, ORGANIZATION_ID)
            product = verify_db.get(SupplyChainEntity, UUID(result_summary["product_entity_id"]))
            market = verify_db.get(SupplyChainEntity, UUID(result_summary["market_entity_id"]))
            event = verify_db.get(DisruptionEvent, UUID(result_summary["event_id"]))
            relationship = verify_db.get(SupplyChainRelationship, UUID(result_summary["relationship_id"]))
            if org is None or product is None or market is None or event is None or relationship is None:
                raise RuntimeError("Post-commit verification failed: an expected record is missing.")
            persisted_impact = calculate_downstream_impact(
                verify_db, org, product.id, max_depth=4, event_id=event.id
            )
            persisted_names = [item["entity"].name for item in persisted_impact["affected_entities"]]
            if MARKET_ENTITY_NAME not in persisted_names:
                raise RuntimeError("Post-commit graph-impact verification failed.")
            result_summary["affected_entities"] = persisted_names
            print(json.dumps(result_summary, indent=2, ensure_ascii=False))
            print("\nREAL-EVIDENCE DISRUPTION ACCEPTANCE PASSED.")
            print("Manual source import, event, graph edge and impact were persisted.")
            print("No external model/provider calls were made by this script.")
            print("The likelihood index is experimental and not a calibrated probability.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
