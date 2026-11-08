"""Audit schemas for the append-only event trail."""

from datetime import datetime
from enum import Enum

from pydantic import Field

from .base import CamelModel


class AuditStatus(str, Enum):
    """Status level of an audit event."""

    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"
    INFO = "info"


class AuditEvent(CamelModel):
    """Individual recorded audit event matching frontend timeline."""

    id: str
    exception_id: str
    timestamp: str | datetime
    action: str
    user: str
    status: str
    trace_id: str
    detail: str | None = None
    flags: list[str] = Field(default_factory=list)
