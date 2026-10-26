"""Persist per-investigation provider request/token accounting.

Revision ID: 0003_exec_metrics
Revises: 0002_intelligence_pipeline
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_exec_metrics"
down_revision: Union[str, None] = "0002_intelligence_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investigation_jobs",
        sa.Column("execution_metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("investigation_jobs", "execution_metrics")
