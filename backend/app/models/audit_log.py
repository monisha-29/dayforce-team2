"""SQLAlchemy model for the audit_log table."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.exception import ExceptionModel


class AuditEventModel(Base):
    """Chronological append-only event recorded for audit trails."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    exception_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("exceptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    user: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Relationships
    exception: Mapped["ExceptionModel | None"] = relationship(
        "ExceptionModel", back_populates="audit_events"
    )
