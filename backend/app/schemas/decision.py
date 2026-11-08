"""Decision schemas for manager review actions."""

from enum import Enum

from .base import CamelModel
from .common import Timecard


class DecisionType(str, Enum):
    """Permitted manager decision actions."""

    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class DecisionRequest(CamelModel):
    """Request payload submitted when a manager reviews a proposal."""

    decision: DecisionType
    edited_timecard: Timecard | None = None
    reason: str | None = None


class DecisionResponse(CamelModel):
    """Response returned upon successfully recording a manager decision."""

    exception_id: str
    new_status: str
    message: str
    trace_id: str


class EscalateRequest(CamelModel):
    """Request payload for manual manager or agent escalation."""

    note: str | None = None
