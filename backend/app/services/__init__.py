"""Services package for backend business and integration logic."""

from app.services.audit_service import (
    generate_audit_id,
    generate_trace_id,
    get_all_audit_events,
    get_audit_events_for_exception,
    log_audit_event,
    to_audit_event_schema,
)
from app.services.dataset_service import (
    DatasetLoadResult,
    load_dataset_from_dict,
    load_dataset_from_file,
)
from app.services.decision_service import (
    escalate_exception_workflow,
    record_decision,
)
from app.services.detector_service import (
    RULES_MODULE_AVAILABLE,
    DetectionSummary,
    DetectorFunction,
    RulesModuleNotAvailableError,
    convert_detector_exception_to_model,
    generate_deterministic_exception_id,
    run_detection_pipeline,
    to_detector_punch,
    to_detector_schedule,
)
from app.services.policy_service import (
    PolicyClauseRecord,
    PolicyService,
    policy_service,
)
from app.services.proposal_service import generate_proposal_for_exception
from app.services.rules_adapter import (
    CHECK_NAME_MAP,
    ValidationSummary,
    compute_net_hours,
    generate_fallback_proposal,
    llm_proposal_to_timecard,
    timecard_to_llm_proposal,
    to_detector_exception,
    validate_timecard_proposal,
    validation_result_to_validator_results,
)

__all__ = [
    "CHECK_NAME_MAP",
    "RULES_MODULE_AVAILABLE",
    "DatasetLoadResult",
    "DetectionSummary",
    "DetectorFunction",
    "PolicyClauseRecord",
    "PolicyService",
    "RulesModuleNotAvailableError",
    "ValidationSummary",
    "compute_net_hours",
    "convert_detector_exception_to_model",
    "escalate_exception_workflow",
    "generate_audit_id",
    "generate_deterministic_exception_id",
    "generate_fallback_proposal",
    "generate_proposal_for_exception",
    "generate_trace_id",
    "get_all_audit_events",
    "get_audit_events_for_exception",
    "llm_proposal_to_timecard",
    "load_dataset_from_dict",
    "load_dataset_from_file",
    "log_audit_event",
    "policy_service",
    "record_decision",
    "run_detection_pipeline",
    "timecard_to_llm_proposal",
    "to_audit_event_schema",
    "to_detector_exception",
    "to_detector_punch",
    "to_detector_schedule",
    "validate_timecard_proposal",
    "validation_result_to_validator_results",
]
