"""Proposal schemas matching PROJECT_SPEC.md and frontend UI contracts."""

from datetime import datetime
from enum import Enum

from pydantic import Field

from .base import CamelModel
from .common import Timecard


class ValidatorName(str, Enum):
    """The five standard validation check names."""

    SCHEMA_VALIDATION = "Schema Validation"
    POLICY_CITATION_VALIDATION = "Policy Citation Validation"
    WORKING_HOURS_VALIDATION = "Working Hours Validation"
    NEW_VIOLATION_CHECK = "New Violation Check"
    VALUE_BOUNDS_CHECK = "Value Bounds Check"


class ValidatorResult(CamelModel):
    """Result of an individual proposal safety check."""

    name: str
    passed: bool
    reason: str | None = None


class ProposedPunch(CamelModel):
    """An individual punch suggested in a proposal."""

    punch_type: str
    timestamp: datetime
    action: str = "insert"
    employee_id: str | None = None
    notes: str | None = None


class Proposal(CamelModel):
    """Proposal generated for resolving a timecard exception."""

    id: str
    exception_id: str
    proposed: Timecard
    changed_fields: list[str] = Field(default_factory=list)
    detected_issue: str
    reason: str
    policy_title: str
    policy_clause_id: str
    policy_excerpt: str
    recommendation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    missing_information: list[str] = Field(default_factory=list)
    validators: list[ValidatorResult] = Field(default_factory=list)
    blocked: bool = False
    generated_at: str | datetime
