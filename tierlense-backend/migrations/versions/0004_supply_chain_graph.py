"""Add evidence-backed supply-chain graph and disruption intelligence.

Revision ID: 0004_supply_chain_graph
Revises: 0003_exec_metrics
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_supply_chain_graph"
down_revision: Union[str, None] = "0003_exec_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investigation_findings",
        sa.Column("structured_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.create_table(
        "supply_chain_entities",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("identity_status", sa.String(length=32), nullable=False),
        sa.Column("resolution_confidence", sa.Float(), nullable=False),
        sa.Column("is_root", sa.Boolean(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "normalized_name", "entity_type", name="uq_supply_entity_name_type"),
    )
    op.create_index("ix_supply_entities_org_type", "supply_chain_entities", ["organization_id", "entity_type"])
    op.create_index("ix_supply_entities_org_country", "supply_chain_entities", ["organization_id", "country_code"])

    op.create_table(
        "supply_chain_relationships",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=48), nullable=False),
        sa.Column("component_or_service", sa.String(length=500), nullable=True),
        sa.Column("ownership_percentage", sa.Float(), nullable=True),
        sa.Column("is_state_owned", sa.Boolean(), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("as_of_date", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_finding_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_passage", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_entity_id"], ["supply_chain_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["supply_chain_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_document_id"], ["evidence_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_finding_id"], ["investigation_findings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "fingerprint", name="uq_supply_relationship_fingerprint"),
    )
    op.create_index("ix_supply_relationships_org_source", "supply_chain_relationships", ["organization_id", "source_entity_id"])
    op.create_index("ix_supply_relationships_org_target", "supply_chain_relationships", ["organization_id", "target_entity_id"])
    op.create_index("ix_supply_relationships_type", "supply_chain_relationships", ["organization_id", "relationship_type"])

    op.create_table(
        "disruption_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("affected_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("event_status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("event_date", sa.String(length=40), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_finding_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_passage", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("is_prediction", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["affected_entity_id"], ["supply_chain_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_document_id"], ["evidence_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_finding_id"], ["investigation_findings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "fingerprint", name="uq_disruption_event_fingerprint"),
    )
    op.create_index("ix_disruption_events_org_entity", "disruption_events", ["organization_id", "affected_entity_id"])
    op.create_index("ix_disruption_events_org_status", "disruption_events", ["organization_id", "event_status"])

    op.create_table(
        "disruption_likelihood_assessments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experimental_index", sa.Float(), nullable=False),
        sa.Column("band", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("is_experimental", sa.Boolean(), nullable=False),
        sa.Column("is_calibrated", sa.Boolean(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["supply_chain_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_disruption_assessment_org_entity_time", "disruption_likelihood_assessments",
        ["organization_id", "entity_id", "assessed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_disruption_assessment_org_entity_time", table_name="disruption_likelihood_assessments")
    op.drop_table("disruption_likelihood_assessments")
    op.drop_index("ix_disruption_events_org_status", table_name="disruption_events")
    op.drop_index("ix_disruption_events_org_entity", table_name="disruption_events")
    op.drop_table("disruption_events")
    op.drop_index("ix_supply_relationships_type", table_name="supply_chain_relationships")
    op.drop_index("ix_supply_relationships_org_target", table_name="supply_chain_relationships")
    op.drop_index("ix_supply_relationships_org_source", table_name="supply_chain_relationships")
    op.drop_table("supply_chain_relationships")
    op.drop_index("ix_supply_entities_org_country", table_name="supply_chain_entities")
    op.drop_index("ix_supply_entities_org_type", table_name="supply_chain_entities")
    op.drop_table("supply_chain_entities")
    op.drop_column("investigation_findings", "structured_details")
