"""SQLAlchemy model for the employees table."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.exception import ExceptionModel
    from app.models.punch import PunchModel
    from app.models.schedule import ScheduleModel


class EmployeeModel(Base):
    """Employee master record."""

    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    shift: Mapped[str] = mapped_column(String(64), nullable=False)
    shift_start: Mapped[str] = mapped_column(String(16), nullable=False)
    shift_end: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    schedules: Mapped[list["ScheduleModel"]] = relationship(
        "ScheduleModel", back_populates="employee", cascade="all, delete-orphan"
    )
    punches: Mapped[list["PunchModel"]] = relationship(
        "PunchModel", back_populates="employee", cascade="all, delete-orphan"
    )
    exceptions: Mapped[list["ExceptionModel"]] = relationship(
        "ExceptionModel", back_populates="employee", cascade="all, delete-orphan"
    )
