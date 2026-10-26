"""Create organization, watch-profile, and investigation-job tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("identity_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_name", "organizations", ["name"], unique=False)

    op.create_table(
        "watch_profiles",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dependency_role", sa.String(length=100), nullable=False),
        sa.Column("products_services", sa.JSON(), nullable=False),
        sa.Column("dependency_context", sa.Text(), nullable=True),
        sa.Column("criticality", sa.String(length=16), nullable=False),
        sa.Column("identity_clues", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id"),
    )

    op.create_table(
        "investigation_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investigation_jobs_organization_id", "investigation_jobs", ["organization_id"], unique=False)
    op.create_index("ix_investigation_jobs_status", "investigation_jobs", ["status"], unique=False)
    op.create_index(
        "ix_investigation_jobs_status_scheduled_at",
        "investigation_jobs",
        ["status", "scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_investigation_jobs_status_scheduled_at", table_name="investigation_jobs")
    op.drop_index("ix_investigation_jobs_status", table_name="investigation_jobs")
    op.drop_index("ix_investigation_jobs_organization_id", table_name="investigation_jobs")
    op.drop_table("investigation_jobs")
    op.drop_table("watch_profiles")
    op.drop_index("ix_organizations_name", table_name="organizations")
    op.drop_table("organizations")
