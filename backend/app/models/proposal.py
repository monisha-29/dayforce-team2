"""SQLAlchemy model for the proposals table."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.decision import DecisionModel
    from app.models.exception import ExceptionModel


class ProposalModel(Base):
    """AI-proposed or rule-fallback resolution for an attendance exception."""

    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    exception_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("exceptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposed_timecard: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    detected_issue: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_title: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_clause_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    validators: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    exception: Mapped["ExceptionModel"] = relationship(
        "ExceptionModel", foreign_keys=[exception_id], back_populates="proposals"
    )
    decision: Mapped["DecisionModel | None"] = relationship(
        "DecisionModel", back_populates="proposal", uselist=False, cascade="all, delete-orphan"
    )
