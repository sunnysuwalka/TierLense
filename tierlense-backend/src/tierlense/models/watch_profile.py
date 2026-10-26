"""Operator-supplied context for monitoring an organization."""

from uuid import UUID

from sqlalchemy import ForeignKey, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tierlense.db.base import Base


class WatchProfile(Base):
    __tablename__ = "watch_profiles"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dependency_role: Mapped[str] = mapped_column(
        String(100), nullable=False, default="supplier"
    )
    products_services: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    dependency_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticality: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium"
    )
    identity_clues: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    organization: Mapped["Organization"] = relationship(back_populates="watch_profile")
