"""Add durable worker state and evidence-first investigation records.

Revision ID: 0002_intelligence_pipeline
Revises: 0001_initial
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_intelligence_pipeline"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("investigation_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("investigation_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("investigation_jobs", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.add_column("investigation_jobs", sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False))
    op.add_column("investigation_jobs", sa.Column("progress_message", sa.String(length=500), nullable=True))
    op.add_column("investigation_jobs", sa.Column("result_summary", sa.JSON(), nullable=True))
    # Backfill before enforcing NOT NULL. A non-constant CURRENT_TIMESTAMP server
    # default cannot be added to an existing SQLite table, so use a portable
    # nullable-add/backfill/batch-alter sequence. SQLAlchemy supplies updated_at
    # for new ORM records; worker updates set it explicitly.
    op.add_column(
        "investigation_jobs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("UPDATE investigation_jobs SET updated_at = created_at WHERE updated_at IS NULL"))
    with op.batch_alter_table("investigation_jobs") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.create_index("ix_investigation_jobs_next_attempt_at", "investigation_jobs", ["next_attempt_at"])

    op.create_table(
        "discovered_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
    )
    op.create_index("ix_discovered_sources_domain", "discovered_sources", ["source_domain"])

    op.create_table(
        "evidence_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["discovered_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_evidence_source_content_hash"),
    )
    op.create_index("ix_evidence_documents_fetched_at", "evidence_documents", ["fetched_at"])

    op.create_table(
        "investigation_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evidence_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("search_query", sa.String(length=1000), nullable=True),
        sa.Column("discovery_snippet", sa.Text(), nullable=True),
        sa.Column("relevant", sa.Boolean(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("relevance_reason", sa.Text(), nullable=True),
        sa.Column("relevance_categories", sa.JSON(), nullable=False),
        sa.Column("fetch_status", sa.String(length=32), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["investigation_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["discovered_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_document_id"], ["evidence_documents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "source_id", name="uq_investigation_source_job_source"),
    )
    op.create_index("ix_investigation_sources_job_relevant", "investigation_sources", ["job_id", "relevant"])

    op.create_table(
        "investigation_findings",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("investigation_source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evidence_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=48), nullable=False),
        sa.Column("subject_name", sa.String(length=500), nullable=False),
        sa.Column("predicate", sa.String(length=255), nullable=False),
        sa.Column("object_value", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("event_status", sa.String(length=48), nullable=False),
        sa.Column("event_date", sa.String(length=40), nullable=True),
        sa.Column("source_passage", sa.Text(), nullable=True),
        sa.Column("model_confidence", sa.Float(), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["investigation_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["investigation_source_id"], ["investigation_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_document_id"], ["evidence_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "fingerprint", name="uq_investigation_finding_job_fingerprint"),
    )
    op.create_index("ix_investigation_findings_job_type", "investigation_findings", ["job_id", "finding_type"])


def downgrade() -> None:
    op.drop_index("ix_investigation_findings_job_type", table_name="investigation_findings")
    op.drop_table("investigation_findings")
    op.drop_index("ix_investigation_sources_job_relevant", table_name="investigation_sources")
    op.drop_table("investigation_sources")
    op.drop_index("ix_evidence_documents_fetched_at", table_name="evidence_documents")
    op.drop_table("evidence_documents")
    op.drop_index("ix_discovered_sources_domain", table_name="discovered_sources")
    op.drop_table("discovered_sources")
    op.drop_index("ix_investigation_jobs_next_attempt_at", table_name="investigation_jobs")
    op.drop_column("investigation_jobs", "updated_at")
    op.drop_column("investigation_jobs", "result_summary")
    op.drop_column("investigation_jobs", "progress_message")
    op.drop_column("investigation_jobs", "progress_percent")
    op.drop_column("investigation_jobs", "worker_id")
    op.drop_column("investigation_jobs", "lease_expires_at")
    op.drop_column("investigation_jobs", "next_attempt_at")
