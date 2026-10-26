import json
import os
from datetime import datetime
from uuid import UUID
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tierlense.core.config import get_settings
from tierlense.models import (
    Organization,
    SupplyChainEntity,
    SupplyChainRelationship,
    EvidenceDocument,
    DiscoveredSource,
)
from tierlense.services.supply_chain import normalize_entity_name, passage_is_in_document

ORG_ID = UUID("6b1162ef-de63-4094-a6a9-cbf887e52f32")
ROOT_ID = UUID("a836f1b0-0200-4ba7-aef6-0742d5729c07")
EDGE_ID = UUID("a8f070cd-7297-467a-aa96-855d6c255a6d")
TARGET_ID = UUID("5fe6b4bb-5f1f-4cf8-b30c-70049be2dc94")
FCA_DOC_ID = UUID("20f86d61-e771-429c-835c-9257a7aaa793")
NVIDIA_DOC_ID = UUID("920ecea2-d8c1-445f-a903-191cd849bc9e")

CANONICAL_NAME = "NVIDIA Corporation"
OLD_NAME = "NVIDIA Corporation - Sprint 2 Live Validation"
APPLY = os.environ.get("TIERLENSE_APPLY_CANONICAL_ROOT_LABEL") == "YES"


def main():
    engine = create_engine(get_settings().database_url)

    try:
        with Session(engine) as db:
            org = db.get(Organization, ORG_ID)
            root = db.get(SupplyChainEntity, ROOT_ID)
            edge = db.get(SupplyChainRelationship, EDGE_ID)
            target = db.get(SupplyChainEntity, TARGET_ID)
            fca_doc = db.get(EvidenceDocument, FCA_DOC_ID)
            nvidia_doc = db.get(EvidenceDocument, NVIDIA_DOC_ID)

            required = {
                "organization": org,
                "root entity": root,
                "relationship": edge,
                "target entity": target,
                "FCA evidence document": fca_doc,
                "NVIDIA evidence document": nvidia_doc,
            }
            missing = [name for name, row in required.items() if row is None]
            if missing:
                raise RuntimeError("Safety check failed; missing: " + ", ".join(missing))

            fca_source = db.get(DiscoveredSource, fca_doc.source_id)
            nvidia_source = db.get(DiscoveredSource, nvidia_doc.source_id)

            if not fca_source or not nvidia_source:
                raise RuntimeError("Evidence source metadata is missing.")

            if (fca_source.canonical_url or "").split("/")[2].lower() != "www.fca.org.uk":
                raise RuntimeError("FCA source URL did not match the expected host.")

            if (nvidia_source.canonical_url or "").split("/")[2].lower() != "www.nvidia.com":
                raise RuntimeError("NVIDIA source URL did not match the expected host.")

            if root.organization_id != ORG_ID or not root.is_root:
                raise RuntimeError("Expected monitored root entity does not match.")

            if edge.organization_id != ORG_ID:
                raise RuntimeError("Relationship belongs to another organization.")

            if edge.source_entity_id != ROOT_ID or edge.target_entity_id != TARGET_ID:
                raise RuntimeError("Relationship endpoints differ from the reviewed record.")

            if edge.evidence_document_id != FCA_DOC_ID:
                raise RuntimeError("Relationship evidence ID differs from the reviewed record.")

            if not passage_is_in_document(edge.source_passage, fca_doc.content_text):
                raise RuntimeError("Stored relationship passage no longer matches its source.")

            if normalize_entity_name(CANONICAL_NAME) != normalize_entity_name("NVIDIA Corporation"):
                raise RuntimeError("Canonical-name normalization check failed.")

            normalized = normalize_entity_name(CANONICAL_NAME)
            conflicting = db.scalar(select(SupplyChainEntity).where(
                SupplyChainEntity.organization_id == ORG_ID,
                SupplyChainEntity.entity_type == "organization",
                SupplyChainEntity.normalized_name == normalized,
                SupplyChainEntity.id != ROOT_ID,
            ))

            if conflicting:
                raise RuntimeError(
                    "A separate NVIDIA entity already exists. No changes made; inspect it first."
                )

            print("\n=== GRAPH ROOT LABEL CORRECTION ===")
            print("External model calls: NONE")
            print(f"Organization profile (unchanged): {org.name}")
            print(f"Graph root: {root.id}")
            print(f"Current graph-root name: {root.name}")
            print(f"Proposed graph-root name: {CANONICAL_NAME}")
            print(f"Relationship ID (preserved): {edge.id}")
            print(f"Relationship type (preserved): {edge.relationship_type}")
            print(f"Target entity (preserved): {target.name}")
            print(f"FCA evidence (verified): {fca_source.canonical_url}")
            print(f"NVIDIA identity reference: {nvidia_source.canonical_url}")
            print("Passage validation: PASS")
            print("Identity status will not be changed automatically.")
            print("The planned-support and draft-source caveats will be retained.")

            if root.name == CANONICAL_NAME:
                print("\nGraph root already has the canonical name; no change needed.")
                return

            if root.name != OLD_NAME:
                raise RuntimeError(
                    "Graph root name differs from the expected test label; "
                    "no changes made."
                )

            if not APPLY:
                print("\nDRY RUN ONLY: database unchanged.")
                print("Review this output. To apply, set the explicit approval variable.")
                return

            backup = {
                "created_at": datetime.now().astimezone().isoformat(),
                "organization_id": str(org.id),
                "organization_name_unchanged": org.name,
                "root": {
                    "id": str(root.id),
                    "name": root.name,
                    "normalized_name": root.normalized_name,
                    "aliases": root.aliases or [],
                    "identity_status": root.identity_status,
                    "attributes": root.attributes or {},
                },
                "relationship": {
                    "id": str(edge.id),
                    "source_entity_id": str(edge.source_entity_id),
                    "target_entity_id": str(edge.target_entity_id),
                    "relationship_type": edge.relationship_type,
                    "evidence_document_id": str(edge.evidence_document_id),
                    "source_passage": edge.source_passage,
                    "fingerprint": edge.fingerprint,
                    "attributes": edge.attributes or {},
                },
            }

            backup_path = Path.cwd() / (
                "tierlense_nvidia_graph_label_backup_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".json"
            )
            backup_path.write_text(
                json.dumps(backup, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            aliases = list(root.aliases or [])
            if OLD_NAME not in aliases:
                aliases.append(OLD_NAME)

            root.name = CANONICAL_NAME
            root.normalized_name = normalized
            root.aliases = aliases

            attributes = dict(root.attributes or {})
            attributes["canonicalization_review"] = {
                "method": "manual_review_of_existing_NVIDIA_and_FCA_sources",
                "canonical_name": CANONICAL_NAME,
                "source_document_ids": [str(NVIDIA_DOC_ID), str(FCA_DOC_ID)],
                "monitoring_profile_name_remains_test_labeled": True,
                "relationship_claim_remains_announced_or_planned": True,
                "fca_source_warns_draft_may_differ_from_delivered_speech": True,
                "not_a_procurement_or_ownership_claim": True,
                "no_model_inference_used": True,
            }
            root.attributes = attributes

            edge_attributes = dict(edge.attributes or {})
            edge_attributes["claim_temporality"] = "announced_or_planned"
            edge_attributes["source_warns_draft_may_differ_from_delivered_speech"] = True
            edge_attributes["not_a_procurement_or_ownership_claim"] = True
            edge_attributes["confidence_is_calibrated"] = False
            edge_attributes["model_inference_used"] = False
            edge.attributes = edge_attributes

            db.commit()
            db.refresh(root)
            db.refresh(edge)

            print("\nCORRECTION APPLIED.")
            print(f"Backup: {backup_path}")
            print(f"Graph root now: {root.name}")
            print(f"Root ID preserved: {root.id}")
            print(f"Relationship ID preserved: {edge.id}")
            print("Organization profile name unchanged.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
