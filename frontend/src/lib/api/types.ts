// Frontend contract for the FastAPI backend. Replace/regenerate from the OpenAPI schema
// (e.g. `openapi-typescript`) once available; keep field names in sync.

export type ExceptionType =
  "Missing Punch" | "Overtime Risk" | "Schedule Conflict" | "Meal Break Violation";
export type Severity = "Low" | "Medium" | "High" | "Critical";
export type ExceptionStatus =
  "Pending Review" | "AI Processing" | "Awaiting Approval" | "Approved" | "Rejected" | "Escalated";

export interface Employee {
  id: string;
  name: string;
  department: string;
  shift: string;
  shiftStart: string;
  shiftEnd: string;
}

export interface Timecard {
  checkIn: string | null;
  checkOut: string | null;
  mealStart: string | null;
  mealEnd: string | null;
  totalHours: number | null;
}

export type ValidatorName =
  | "Schema Validation"
  | "Policy Citation Validation"
  | "Working Hours Validation"
  | "New Violation Check"
  | "Value Bounds Check";

export interface ValidatorResult {
  name: ValidatorName;
  passed: boolean;
  reason?: string;
}

export interface Proposal {
  id: string;
  exceptionId: string;
  proposed: Timecard;
  changedFields: (keyof Timecard)[];
  detectedIssue: string;
  reason: string;
  policyTitle: string;
  policyClauseId: string;
  policyExcerpt: string;
  recommendation: string;
  confidence: number; // 0..1
  missingInformation: string[];
  validators: ValidatorResult[];
  blocked: boolean;
  generatedAt: string;
}

export interface AttendanceException {
  id: string;
  employee: Employee;
  type: ExceptionType;
  date: string; // ISO date
  severity: Severity;
  status: ExceptionStatus;
  original: Timecard;
  proposalId: string | null;
  detectedAt: string;
}

export interface ExceptionDetail extends AttendanceException {
  proposal: Proposal | null;
}

export type AuditAction =
  | "Exception detected"
  | "Policy retrieved"
  | "AI proposal generated"
  | "Validation completed"
  | "Retry attempted"
  | "Fallback triggered"
  | "Escalated"
  | "Manager approved"
  | "Manager edited"
  | "Manager rejected"
  | "Timecard updated";

export interface AuditEvent {
  id: string;
  exceptionId: string;
  timestamp: string;
  action: AuditAction;
  user: string;
  status: "success" | "warning" | "failure" | "info";
  traceId: string;
  detail?: string;
  flags: ("Retried" | "Fallback" | "Escalated")[];
}

export type DecisionType = "approve" | "edit" | "reject";

export interface DecisionRequest {
  decision: DecisionType;
  editedTimecard?: Timecard;
  reason?: string;
}

export interface DecisionResponse {
  exceptionId: string;
  newStatus: ExceptionStatus;
  message: string;
  traceId: string;
}

export interface ExceptionFilters {
  search?: string;
  type?: ExceptionType | "all";
  status?: ExceptionStatus | "all";
  severity?: Severity | "all";
}
