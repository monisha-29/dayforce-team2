"""Rules and Validation Engine for Timecard Exception Agent (Person 3).

Exposes:
- HoursCalculator: Deterministic hours, break, and overtime calculation.
- Four Exception Detectors: MissedPunchDetector, OvertimeDetector, ScheduleConflictDetector, MealBreakDetector.
- ProposalValidator: 5-check safety validator for LLM proposals.
- FallbackEngine: Rule-based deterministic fallback mechanism.
- PolicyRegistry: Policy loading and verification.
"""

from .detectors import (
    BaseDetector,
    MealBreakDetector,
    MissedPunchDetector,
    OvertimeDetector,
    RulesConfig,
    ScheduleConflictDetector,
    detect_all_exceptions,
    detect_shift_exceptions,
)
from .fallback import FallbackEngine
from .hours_calculator import (
    BreakInterval,
    CalculatorConfig,
    DailyHoursResult,
    HoursCalculator,
    ShiftInterval,
    WeeklyHoursResult,
)
from .models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    Severity,
    TimecardException,
)
from .models.proposal import (
    LLMProposal,
    ProposedPunch,
)
from .models.validation import (
    FallbackResult,
    ValidationCheckDetail,
    ValidationErrorItem,
    ValidationResult,
)
from .policy_loader import (
    DEFAULT_POLICY_CLAUSES,
    PolicyClause,
    PolicyRegistry,
    policy_registry,
)
from .validator import ProposalValidator

__all__ = [
    "DEFAULT_POLICY_CLAUSES",
    "BaseDetector",
    "BreakInterval",
    "CalculatorConfig",
    "DailyHoursResult",
    "ExceptionType",
    "FallbackEngine",
    "FallbackResult",
    "HoursCalculator",
    "LLMProposal",
    "MealBreakDetector",
    "MissedPunchDetector",
    "OvertimeDetector",
    "PolicyClause",
    "PolicyRegistry",
    "ProposalValidator",
    "ProposedPunch",
    "Punch",
    "PunchType",
    "RulesConfig",
    "Schedule",
    "ScheduleConflictDetector",
    "Severity",
    "ShiftInterval",
    "TimecardException",
    "ValidationCheckDetail",
    "ValidationErrorItem",
    "ValidationResult",
    "WeeklyHoursResult",
    "detect_all_exceptions",
    "detect_shift_exceptions",
    "policy_registry",
]
