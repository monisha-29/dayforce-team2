// Frontend contract for the FastAPI backend. Replace/regenerate from the OpenAPI schema
// (e.g. `openapi-typescript`) once available; keep field names in sync.

export type ExceptionType =
  | "Missing Punch"
  | "Overtime Risk"
  | "Schedule Conflict"
  | "Meal Break Violation"
  | "Duplicate Punch"
  | "Rest Period Violation"
  | "Consecutive Days";
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

export type PunchKind = "IN" | "OUT" | "BREAK_START" | "BREAK_END";

/** One recorded punch of the shift behind an exception (duplicates included). */
export interface PunchRecord {
  id: string;
  type: PunchKind;
  date: string;
  time: string;
  source: string;
  notes: string | null;
  isDuplicate: boolean;
}

/** Another shift of the same employee that explains a multi-day exception. */
export interface ContextShift {
  date: string;
  start: string;
  end: string | null;
  endDate: string | null;
}

export interface ExceptionDetail extends AttendanceException {
  /** The detector's own description of what is wrong. Absent in the mock data. */
  detectedIssue?: string;
  proposal: Proposal | null;
  /** Absent in the in-browser mock data. */
  punches?: PunchRecord[];
  schedule?: { start: string; end: string } | null;
  /** Rest-period and consecutive-days exceptions: the shifts that explain them. */
  contextShifts?: ContextShift[];
  contextSummary?: string | null;
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

export type AttendanceStatus = "Present" | "Late" | "Absent";

export interface AttendanceRecord {
  employeeId: string;
  name: string;
  department: string;
  shift: string;
  scheduledStart: string | null;
  scheduledEnd: string | null;
  checkIn: string | null;
  checkOut: string | null;
  status: AttendanceStatus;
  exceptionIds: string[];
}

export interface AttendanceDay {
  date: string;
  minDate: string | null;
  maxDate: string | null;
  records: AttendanceRecord[];
}

export interface DayCount {
  date: string;
  label: string;
  present: number;
  late: number;
  absent: number;
}

export interface WeekRate {
  week: string;
  start: string;
  rate: number | null;
  exceptions: number;
}

export interface AttendanceSummary {
  date: string;
  totalEmployees: number;
  departments: number;
  scheduled: number;
  present: number;
  late: number;
  absent: number;
  days: DayCount[];
  weeks: WeekRate[];
}
