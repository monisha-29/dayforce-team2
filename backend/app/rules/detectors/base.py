"""Base class and common utilities for exception detectors."""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence

from ..models.exception import (
    ExceptionType,
    Punch,
    Schedule,
    TimecardException,
)


class BaseDetector(ABC):
    """Abstract base class for all timecard exception detectors."""

    @property
    @abstractmethod
    def exception_type(self) -> ExceptionType:
        """The specific exception type this detector handles."""

    @abstractmethod
    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        """Inspect punches and schedule to return any detected exceptions."""

    def generate_exception_id(
        self,
        employee_id: str,
        date_str: str,
        sub_type: str,
    ) -> str:
        """Generate a deterministic, reproducible exception ID to prevent duplicates."""
        namespace = uuid.UUID("12345678-1234-5678-1234-567812345678")
        name = f"{employee_id}_{date_str}_{self.exception_type.value}_{sub_type}"
        return f"EXC-{uuid.uuid5(namespace, name).hex[:12].upper()}"
