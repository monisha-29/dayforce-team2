"""SQLAlchemy model for the decisions table."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.exception import ExceptionModel
    from app.models.proposal import ProposalModel


class DecisionModel(Base):
    """Manager decision record (approve, edit, or reject) for an exception proposal."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    exception_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("exceptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    manager_user: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_timecard: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    proposal: Mapped["ProposalModel | None"] = relationship(
        "ProposalModel", back_populates="decision"
    )
    exception: Mapped["ExceptionModel"] = relationship("ExceptionModel", back_populates="decisions")
