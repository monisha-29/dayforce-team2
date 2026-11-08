"""Data models for validation results, errors, checks, and fallback outcomes."""

from typing import Any

from pydantic import BaseModel, Field


class ValidationErrorItem(BaseModel):
    """Structured validation error suitable for Person 4's LLM retry loop.

    Example:
    {
      "code": "OVERTIME_LIMIT_EXCEEDED",
      "message": "Proposed shift creates 9.5 working hours. Configured daily limit is 8 hours.",
      "field": "proposed_punches"
    }
    """

    code: str
    message: str
    field: str | None = None


class ValidationCheckDetail(BaseModel):
    """Detailed status for an individual validation check."""

    check_name: str
    passed: bool
    message: str
    details: dict[str, Any] | None = None


class ValidationResult(BaseModel):
    """Complete structured response returned by Person 3's validator.

    Contains all required fields:
    - valid: bool
    - status: str ("PASSED" | "FAILED")
    - errors: list of ValidationErrorItem
    - warnings: list of str
    - validation_checks: dict of bool flags for the 5 checks
    - validated_working_hours: recalculated float hours or None
    - cited_policy_ids: list of validated policy clause IDs
    - explanation: manager-facing and LLM-readable summary
    """

    valid: bool
    status: str  # "PASSED" or "FAILED"
    errors: list[ValidationErrorItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_checks: dict[str, bool] = Field(
        default_factory=lambda: {
            "format_valid": False,
            "policy_clauses_valid": False,
            "working_hours_valid": False,
            "no_new_violations": False,
            "limits_valid": False,
        }
    )
    check_details: list[ValidationCheckDetail] = Field(default_factory=list)
    validated_working_hours: float | None = None
    cited_policy_ids: list[str] = Field(default_factory=list)
    explanation: str = ""


class FallbackResult(BaseModel):
    """Structured response returned by the rule-based fallback mechanism.

    Contains all required fields:
    - success: bool
    - exception_id: str
    - proposed_correction: Optional dict of corrected punches/shifts
    - reason: str
    - validation_result: Optional[ValidationResult]
    - requires_manager_review: bool
    """

    success: bool
    exception_id: str
    proposed_correction: dict[str, Any] | None = None
    reason: str
    validation_result: ValidationResult | None = None
    requires_manager_review: bool = True
