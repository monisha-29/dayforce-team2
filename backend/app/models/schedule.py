"""SQLAlchemy model for the schedules table."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.employee import EmployeeModel


class ScheduleModel(Base):
    """Assigned shift schedule for an employee."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_break_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # Relationships
    employee: Mapped["EmployeeModel"] = relationship("EmployeeModel", back_populates="schedules")
