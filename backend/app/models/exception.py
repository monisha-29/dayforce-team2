"""SQLAlchemy model for the exceptions table."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.audit_log import AuditEventModel
    from app.models.decision import DecisionModel
    from app.models.employee import EmployeeModel
    from app.models.proposal import ProposalModel


class ExceptionModel(Base):
    """Detected attendance exception and review lifecycle status."""

    __tablename__ = "exceptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), default="medium", nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_review", nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    original_attendance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    proposal_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("proposals.id", use_alter=True, name="fk_exceptions_proposal_id"),
        nullable=True,
    )
    policy_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    employee: Mapped["EmployeeModel"] = relationship("EmployeeModel", back_populates="exceptions")
    active_proposal: Mapped["ProposalModel | None"] = relationship(
        "ProposalModel",
        foreign_keys=[proposal_id],
        post_update=True,
    )
    proposals: Mapped[list["ProposalModel"]] = relationship(
        "ProposalModel",
        foreign_keys="ProposalModel.exception_id",
        back_populates="exception",
        cascade="all, delete-orphan",
    )
    decisions: Mapped[list["DecisionModel"]] = relationship(
        "DecisionModel", back_populates="exception", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEventModel"]] = relationship(
        "AuditEventModel", back_populates="exception", cascade="all, delete-orphan"
    )
