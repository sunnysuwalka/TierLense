"""Autonomous scheduling, evidence changes, snapshots and supplier recommendations.

Revision ID: 0005_sprint4_ops
Revises: 0004_supply_chain_graph
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005_sprint4_ops"
down_revision: Union[str, None] = "0004_supply_chain_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("discovered_sources", sa.Column("latest_content_hash", sa.String(length=64), nullable=True))
    op.add_column("discovered_sources", sa.Column("latest_document_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("discovered_sources", sa.Column("last_content_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "investigation_schedules",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_job_id"], ["investigation_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_investigation_schedule_organization"),
    )
    op.create_index("ix_investigation_schedules_due", "investigation_schedules", ["enabled", "next_run_at"])

    # Existing organizations receive a default daily schedule. New organizations
    # create the same row transactionally during onboarding.
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    bind = op.get_bind()
    organization_table = sa.table("organizations", sa.column("id", sa.Uuid(as_uuid=True)))
    schedule_table = sa.table(
        "investigation_schedules",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("organization_id", sa.Uuid(as_uuid=True)),
        sa.column("enabled", sa.Boolean()),
        sa.column("interval_minutes", sa.Integer()),
        sa.column("next_run_at", sa.DateTime(timezone=True)),
        sa.column("last_enqueued_at", sa.DateTime(timezone=True)),
        sa.column("last_success_at", sa.DateTime(timezone=True)),
        sa.column("last_job_id", sa.Uuid(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    organization_ids = list(bind.execute(sa.select(organization_table.c.id)).scalars())
    for organization_id in organization_ids:
        bind.execute(sa.insert(schedule_table).values(
            id=uuid4(), organization_id=organization_id, enabled=True, interval_minutes=1440,
            next_run_at=now + timedelta(days=1), last_enqueued_at=None, last_success_at=None,
            last_job_id=None, created_at=now, updated_at=now,
        ))

    op.create_table(
        "evidence_changes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("previous_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("current_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("previous_content_hash", sa.String(length=64), nullable=True),
        sa.Column("current_content_hash", sa.String(length=64), nullable=False),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("reassessment_status", sa.String(length=32), nullable=False),
        sa.Column("reassessment_details", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["investigation_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["discovered_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["previous_document_id"], ["evidence_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["current_document_id"], ["evidence_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_changes_org_detected", "evidence_changes", ["organization_id", "detected_at"])
    op.create_index("ix_evidence_changes_job_status", "evidence_changes", ["job_id", "reassessment_status"])

    op.create_table(
        "investigation_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("evidence_document_ids", sa.JSON(), nullable=False),
        sa.Column("finding_ids", sa.JSON(), nullable=False),
        sa.Column("graph_entity_ids", sa.JSON(), nullable=False),
        sa.Column("graph_relationship_ids", sa.JSON(), nullable=False),
        sa.Column("disruption_event_ids", sa.JSON(), nullable=False),
        sa.Column("risk_assessment_ids", sa.JSON(), nullable=False),
        sa.Column("graph_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_change_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["investigation_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_investigation_snapshot_job"),
    )
    op.create_index("ix_investigation_snapshots_org_time", "investigation_snapshots", ["organization_id", "snapshot_at"])

    op.create_table(
        "supplier_recommendations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("affected_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_job_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("required_function", sa.String(length=500), nullable=False),
        sa.Column("required_role", sa.String(length=100), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("result_status", sa.String(length=32), nullable=False),
        sa.Column("scoring_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["affected_entity_id"], ["supply_chain_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_job_id"], ["investigation_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplier_recommendations_org_time", "supplier_recommendations", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_supplier_recommendations_org_time", table_name="supplier_recommendations")
    op.drop_table("supplier_recommendations")
    op.drop_index("ix_investigation_snapshots_org_time", table_name="investigation_snapshots")
    op.drop_table("investigation_snapshots")
    op.drop_index("ix_evidence_changes_job_status", table_name="evidence_changes")
    op.drop_index("ix_evidence_changes_org_detected", table_name="evidence_changes")
    op.drop_table("evidence_changes")
    op.drop_index("ix_investigation_schedules_due", table_name="investigation_schedules")
    op.drop_table("investigation_schedules")
    op.drop_column("discovered_sources", "last_content_changed_at")
    op.drop_column("discovered_sources", "latest_document_id")
    op.drop_column("discovered_sources", "latest_content_hash")
