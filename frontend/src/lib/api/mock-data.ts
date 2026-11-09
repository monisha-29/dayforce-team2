// Fictional synthetic data. No real employees.
import type {
  AttendanceException,
  AuditEvent,
  Employee,
  ExceptionStatus,
  ExceptionType,
  Proposal,
  Severity,
  Timecard,
  ValidatorResult,
} from "./types";

const shifts = {
  day: { shift: "Day Shift", shiftStart: "09:00", shiftEnd: "18:00" },
  early: { shift: "Early Shift", shiftStart: "06:00", shiftEnd: "14:30" },
  late: { shift: "Late Shift", shiftStart: "14:00", shiftEnd: "22:30" },
  night: { shift: "Night Shift", shiftStart: "22:00", shiftEnd: "06:30" },
};

export const employees: Employee[] = [
  { id: "EMP-1042", name: "Aarav Mehta", department: "Operations", ...shifts.day },
  { id: "EMP-1057", name: "Lena Fischer", department: "Customer Support", ...shifts.late },
  { id: "EMP-1063", name: "Marcus Bell", department: "Warehouse", ...shifts.early },
  { id: "EMP-1078", name: "Priya Raman", department: "Finance", ...shifts.day },
  { id: "EMP-1081", name: "Diego Alvarez", department: "Warehouse", ...shifts.night },
  { id: "EMP-1094", name: "Hannah Okafor", department: "Nursing", ...shifts.night },
  { id: "EMP-1102", name: "Kenji Watanabe", department: "Engineering", ...shifts.day },
  { id: "EMP-1115", name: "Sofia Rossi", department: "Retail", ...shifts.late },
  { id: "EMP-1123", name: "Omar Haddad", department: "Logistics", ...shifts.early },
  { id: "EMP-1137", name: "Grace Lindqvist", department: "Customer Support", ...shifts.day },
  { id: "EMP-1146", name: "Ravi Iyer", department: "Operations", ...shifts.late },
  { id: "EMP-1150", name: "Chloé Martin", department: "Nursing", ...shifts.early },
  { id: "EMP-1168", name: "Samuel Nkemelu", department: "Logistics", ...shifts.night },
  { id: "EMP-1174", name: "Isabel Duarte", department: "Retail", ...shifts.day },
  { id: "EMP-1189", name: "Tomás Novak", department: "Engineering", ...shifts.day },
  { id: "EMP-1195", name: "Ananya Kulkarni", department: "Finance", ...shifts.day },
];

export const TOTAL_EMPLOYEES = 248;

function hrs(a: string | null, b: string | null, mealMin = 0): number | null {
  if (!a || !b) return null;
  const [ah = 0, am = 0] = a.split(":").map(Number);
  const [bh = 0, bm = 0] = b.split(":").map(Number);
  let m = bh * 60 + bm - (ah * 60 + am);
  if (m < 0) m += 24 * 60;
  return Math.round(((m - mealMin) / 60) * 100) / 100;
}

function mealMins(tc: Pick<Timecard, "mealStart" | "mealEnd">) {
  const h = hrs(tc.mealStart, tc.mealEnd);
  return h ? Math.round(h * 60) : 0;
}

export function computeHours(tc: Omit<Timecard, "totalHours">): number | null {
  return hrs(tc.checkIn, tc.checkOut, mealMins(tc));
}

function tc(
  checkIn: string | null,
  checkOut: string | null,
  mealStart: string | null,
  mealEnd: string | null,
): Timecard {
  return {
    checkIn,
    checkOut,
    mealStart,
    mealEnd,
    totalHours: computeHours({ checkIn, checkOut, mealStart, mealEnd }),
  };
}

const allPass = (): ValidatorResult[] => [
  { name: "Schema Validation", passed: true },
  { name: "Policy Citation Validation", passed: true },
  { name: "Working Hours Validation", passed: true },
  { name: "New Violation Check", passed: true },
  { name: "Value Bounds Check", passed: true },
];

interface Seed {
  emp: number;
  type: ExceptionType;
  day: number; // days before 2026-11-08
  severity: Severity;
  status: ExceptionStatus;
  original: Timecard;
  proposed: Timecard | null;
  changed?: (keyof Timecard)[];
  confidence?: number;
  fail?: { name: ValidatorResult["name"]; reason: string }[];
  missing?: string[];
}

const seeds: Seed[] = [
  {
    emp: 0,
    type: "Missing Punch",
    day: 0,
    severity: "High",
    status: "Awaiting Approval",
    original: tc("09:00", null, "13:00", "13:30"),
    proposed: tc("09:00", "18:00", "13:00", "13:30"),
    changed: ["checkOut", "totalHours"],
    confidence: 0.92,
  },
  {
    emp: 1,
    type: "Overtime Risk",
    day: 0,
    severity: "Critical",
    status: "Awaiting Approval",
    original: tc("14:00", "01:15", "18:00", "18:30"),
    proposed: tc("14:00", "22:30", "18:00", "18:30"),
    changed: ["checkOut", "totalHours"],
    confidence: 0.78,
    fail: [
      {
        name: "Working Hours Validation",
        reason:
          "Proposed check-out truncates 2h45m of badge-verified work; reducing recorded hours below actual presence is not permitted (FLSA-aligned rule WH-04).",
      },
    ],
  },
  {
    emp: 2,
    type: "Meal Break Violation",
    day: 0,
    severity: "Medium",
    status: "Pending Review",
    original: tc("06:00", "14:30", null, null),
    proposed: tc("06:00", "14:30", "10:00", "10:30"),
    changed: ["mealStart", "mealEnd", "totalHours"],
    confidence: 0.64,
    missing: ["Employee attestation that a 30-min meal break was taken"],
  },
  {
    emp: 3,
    type: "Schedule Conflict",
    day: 1,
    severity: "Low",
    status: "Approved",
    original: tc("08:10", "17:05", "12:30", "13:00"),
    proposed: tc("09:00", "17:05", "12:30", "13:00"),
    changed: ["checkIn", "totalHours"],
    confidence: 0.88,
  },
  {
    emp: 4,
    type: "Missing Punch",
    day: 1,
    severity: "High",
    status: "Escalated",
    original: tc(null, "06:40", "02:00", "02:30"),
    proposed: null,
    missing: [
      "No badge, VPN or supervisor log available for check-in",
      "Shift swap record not found",
    ],
  },
  {
    emp: 5,
    type: "Overtime Risk",
    day: 1,
    severity: "Critical",
    status: "Escalated",
    original: tc("22:00", "09:10", "02:00", "02:30"),
    proposed: tc("22:00", "06:30", "02:00", "02:30"),
    changed: ["checkOut", "totalHours"],
    confidence: 0.51,
    fail: [
      {
        name: "Policy Citation Validation",
        reason:
          "Cited clause OT-3.2 does not apply to clinical staff under union agreement NUR-CBA-2025.",
      },
      {
        name: "New Violation Check",
        reason: "Correction would create an unpaid-work violation for patient handover period.",
      },
    ],
  },
  {
    emp: 6,
    type: "Schedule Conflict",
    day: 2,
    severity: "Medium",
    status: "AI Processing",
    original: tc("09:02", "18:10", "13:00", "14:00"),
    proposed: null,
  },
  {
    emp: 7,
    type: "Meal Break Violation",
    day: 2,
    severity: "Medium",
    status: "Awaiting Approval",
    original: tc("14:00", "22:30", "20:45", "20:55"),
    proposed: tc("14:00", "22:30", "18:30", "19:00"),
    changed: ["mealStart", "mealEnd", "totalHours"],
    confidence: 0.71,
    fail: [
      {
        name: "Value Bounds Check",
        reason:
          "Proposed meal window does not match the 10-minute break recorded at the POS terminal; values outside observed bounds.",
      },
    ],
  },
  {
    emp: 8,
    type: "Missing Punch",
    day: 2,
    severity: "Low",
    status: "Rejected",
    original: tc("06:00", null, "10:00", "10:30"),
    proposed: tc("06:00", "14:30", "10:00", "10:30"),
    changed: ["checkOut", "totalHours"],
    confidence: 0.83,
  },
  {
    emp: 9,
    type: "Overtime Risk",
    day: 3,
    severity: "High",
    status: "Pending Review",
    original: tc("08:30", "19:45", "12:30", "13:00"),
    proposed: tc("08:30", "19:45", "12:30", "13:00"),
    changed: [],
    confidence: 0.9,
  },
  {
    emp: 10,
    type: "Missing Punch",
    day: 3,
    severity: "Medium",
    status: "Awaiting Approval",
    original: tc(null, "22:35", "18:00", "18:30"),
    proposed: tc("14:00", "22:35", "18:00", "18:30"),
    changed: ["checkIn", "totalHours"],
    confidence: 0.86,
  },
  {
    emp: 11,
    type: "Schedule Conflict",
    day: 3,
    severity: "High",
    status: "Approved",
    original: tc("05:30", "14:30", "10:00", "10:30"),
    proposed: tc("06:00", "14:30", "10:00", "10:30"),
    changed: ["checkIn", "totalHours"],
    confidence: 0.94,
  },
  {
    emp: 12,
    type: "Meal Break Violation",
    day: 4,
    severity: "Low",
    status: "Approved",
    original: tc("22:00", "06:30", null, null),
    proposed: tc("22:00", "06:30", "02:00", "02:30"),
    changed: ["mealStart", "mealEnd", "totalHours"],
    confidence: 0.81,
  },
  {
    emp: 13,
    type: "Missing Punch",
    day: 4,
    severity: "Medium",
    status: "Pending Review",
    original: tc("09:00", null, null, null),
    proposed: tc("09:00", "18:00", "13:00", "13:30"),
    changed: ["checkOut", "mealStart", "mealEnd", "totalHours"],
    confidence: 0.69,
    missing: ["Meal break punches are absent"],
  },
  {
    emp: 14,
    type: "Overtime Risk",
    day: 4,
    severity: "Medium",
    status: "AI Processing",
    original: tc("08:45", "20:05", "12:00", "12:45"),
    proposed: null,
  },
  {
    emp: 15,
    type: "Schedule Conflict",
    day: 5,
    severity: "Low",
    status: "Awaiting Approval",
    original: tc("10:15", "18:00", "13:00", "13:30"),
    proposed: tc("10:15", "18:00", "13:00", "13:30"),
    changed: [],
    confidence: 0.87,
  },
  {
    emp: 0,
    type: "Meal Break Violation",
    day: 5,
    severity: "Low",
    status: "Rejected",
    original: tc("09:00", "18:00", "13:00", "13:15"),
    proposed: tc("09:00", "18:00", "13:00", "13:30"),
    changed: ["mealEnd", "totalHours"],
    confidence: 0.74,
  },
  {
    emp: 4,
    type: "Overtime Risk",
    day: 5,
    severity: "High",
    status: "Awaiting Approval",
    original: tc("22:00", "08:00", "02:00", "02:30"),
    proposed: tc("22:00", "08:00", "02:00", "02:30"),
    changed: [],
    confidence: 0.91,
  },
  {
    emp: 7,
    type: "Missing Punch",
    day: 6,
    severity: "Critical",
    status: "Escalated",
    original: tc(null, null, null, null),
    proposed: null,
    missing: ["No punches recorded; possible unplanned absence or device outage"],
  },
  {
    emp: 2,
    type: "Schedule Conflict",
    day: 6,
    severity: "Medium",
    status: "Pending Review",
    original: tc("14:00", "22:30", "18:00", "18:30"),
    proposed: tc("14:00", "22:30", "18:00", "18:30"),
    changed: [],
    confidence: 0.77,
    missing: ["Approved shift-swap request from Early to Late shift"],
  },
  {
    emp: 9,
    type: "Missing Punch",
    day: 6,
    severity: "Low",
    status: "Approved",
    original: tc("09:00", "18:00", "13:00", null),
    proposed: tc("09:00", "18:00", "13:00", "13:30"),
    changed: ["mealEnd", "totalHours"],
    confidence: 0.95,
  },
  {
    emp: 11,
    type: "Overtime Risk",
    day: 7,
    severity: "Medium",
    status: "Awaiting Approval",
    original: tc("06:00", "16:10", "10:00", "10:30"),
    proposed: tc("06:00", "16:10", "10:00", "10:30"),
    changed: [],
    confidence: 0.82,
  },
];

const policy: Record<ExceptionType, { title: string; clause: string; excerpt: string }> = {
  "Missing Punch": {
    title: "Timekeeping & Punch Integrity Policy",
    clause: "TK-2.4",
    excerpt:
      "Where a punch is missing, a correction may be proposed from corroborating evidence (badge, system login, supervisor log) and must be approved by the direct manager within 72 hours.",
  },
  "Overtime Risk": {
    title: "Overtime Authorization Policy",
    clause: "OT-3.2",
    excerpt:
      "Hours exceeding 40 per week or 10 per day require prior written authorization. Unauthorized overtime must still be paid and flagged for review; recorded hours may not be reduced.",
  },
  "Schedule Conflict": {
    title: "Scheduling & Shift Adherence Policy",
    clause: "SC-1.7",
    excerpt:
      "Punches more than 15 minutes outside the scheduled shift are flagged. Early punches without authorization are rounded to scheduled start where no work was performed.",
  },
  "Meal Break Violation": {
    title: "Meal & Rest Period Policy",
    clause: "MB-4.1",
    excerpt:
      "Employees working more than 6 hours must receive an uninterrupted unpaid meal period of at least 30 minutes, beginning no later than the end of the 5th hour.",
  },
  "Duplicate Punch": {
    title: "Duplicate Punch Handling",
    clause: "DUP-01",
    excerpt:
      "When the same punch type is recorded twice within 2 minutes, the first punch is kept and the repeat is treated as a terminal double tap. A manager reviews it before it is removed.",
  },
  "Rest Period Violation": {
    title: "Minimum Rest Between Shifts",
    clause: "REST-01",
    excerpt:
      "Employees must have at least 8.0 hours between the end of one shift and the start of the next. Punch times must not be altered to create the required rest.",
  },
  "Consecutive Days": {
    title: "Maximum Consecutive Working Days",
    clause: "CONSEC-01",
    excerpt:
      "No employee may work more than 6 consecutive calendar days without a day off. The 7th consecutive day requires written manager authorization.",
  },
};

const reasons: Record<
  ExceptionType,
  (e: Employee) => { issue: string; reason: string; rec: string }
> = {
  "Missing Punch": (e) => ({
    issue: "Missing clock punch on timecard",
    reason: `No matching punch was recorded for ${e.shift.toLowerCase()} (${e.shiftStart}–${e.shiftEnd}). Building badge exit and system logout events indicate the employee completed the shift.`,
    rec: "Insert the missing punch at the scheduled shift boundary, corroborated by badge and system activity.",
  }),
  "Overtime Risk": (e) => ({
    issue: "Daily hours exceed overtime threshold",
    reason: `Recorded hours exceed the 10-hour daily limit for ${e.department}. No pre-approved overtime request was found.`,
    rec: "Retain actual worked hours, pay overtime, and route to manager for authorization review.",
  }),
  "Schedule Conflict": (e) => ({
    issue: "Punch outside scheduled shift window",
    reason: `Punch deviates more than 15 minutes from the scheduled ${e.shiftStart} start. No authorized early start or shift swap was found.`,
    rec: "Align check-in to the scheduled start where no productive work was recorded before shift.",
  }),
  "Meal Break Violation": () => ({
    issue: "Meal period missing or shorter than 30 minutes",
    reason: "Employee worked more than 6 hours without a compliant 30-minute meal period recorded.",
    rec: "Record a compliant meal period if attested by the employee; otherwise pay meal-period premium.",
  }),
  "Duplicate Punch": () => ({
    issue: "Same punch recorded twice within minutes",
    reason:
      "The same punch type was recorded twice within 2 minutes, which looks like a terminal double tap.",
    rec: "Keep the first punch and remove the repeat once the manager confirms. No hours change.",
  }),
  "Rest Period Violation": () => ({
    issue: "Less than 8 hours of rest between shifts",
    reason:
      "The gap between the previous shift end and this shift start is below the 8-hour minimum.",
    rec: "Do not alter punch times. Document the reason (schedule change or voluntary swap) for manager review.",
  }),
  "Consecutive Days": () => ({
    issue: "More than 6 consecutive days worked",
    reason: "This is the 7th or later consecutive working day without a day off.",
    rec: "Do not alter the attendance record. Manager authorization or a schedule correction is needed.",
  }),
};

const iso = (day: number, time = "08:15") => {
  const d = new Date(Date.UTC(2026, 10, 8 - day));
  const [h = 0, m = 0] = time.split(":").map(Number);
  d.setUTCHours(h, m);
  return d.toISOString();
};

export const exceptions: AttendanceException[] = [];
export const proposals: Record<string, Proposal> = {};
export const audits: Record<string, AuditEvent[]> = {};

const trace = (i: number, j: number) => `tr-${(0x3a7f1 + i * 977 + j * 131).toString(16)}`;

seeds.forEach((s, i) => {
  const e = employees[s.emp]!;
  const id = `EXC-${String(2401 + i)}`;
  const date = iso(s.day).slice(0, 10);
  const p = policy[s.type];
  const r = reasons[s.type](e);
  let proposalId: string | null = null;
  if (s.proposed) {
    proposalId = `PRP-${String(7101 + i)}`;
    const validators = allPass().map((v) => {
      const f = s.fail?.find((x) => x.name === v.name);
      return f ? { ...v, passed: false, reason: f.reason } : v;
    });
    proposals[proposalId] = {
      id: proposalId,
      exceptionId: id,
      proposed: s.proposed,
      changedFields: s.changed ?? [],
      detectedIssue: r.issue,
      reason: r.reason,
      policyTitle: p.title,
      policyClauseId: p.clause,
      policyExcerpt: p.excerpt,
      recommendation: r.rec,
      confidence: s.confidence ?? 0.8,
      missingInformation: s.missing ?? [],
      validators,
      blocked: validators.some((v) => !v.passed),
      generatedAt: iso(s.day, "08:16"),
    };
  }
  exceptions.push({
    id,
    employee: e,
    type: s.type,
    date,
    severity: s.severity,
    status: s.status,
    original: s.original,
    proposalId,
    detectedAt: iso(s.day),
  });

  const ev: AuditEvent[] = [];
  const push = (
    time: string,
    action: AuditEvent["action"],
    status: AuditEvent["status"],
    user: string,
    detail: string | undefined = undefined,
    flags: AuditEvent["flags"] = [],
  ) =>
    ev.push({
      id: `${id}-${ev.length}`,
      exceptionId: id,
      timestamp: iso(s.day, time),
      action,
      status,
      user,
      ...(detail ? { detail } : {}),
      flags,
      traceId: trace(i, ev.length),
    });
  push("08:15", "Exception detected", "info", "Detection Engine", `${s.type} detected on ${date}`);
  push("08:15", "Policy retrieved", "success", "Policy RAG Service", `${p.title} (${p.clause})`);
  const failed = !!s.fail?.length;
  if (i % 4 === 1 || failed)
    push(
      "08:16",
      "Retry attempted",
      "warning",
      "SmartAttend Agent",
      "First proposal failed schema validation; regenerated.",
      ["Retried"],
    );
  if (!s.proposed) {
    if (s.status !== "AI Processing") {
      push(
        "08:17",
        "Fallback triggered",
        "warning",
        "SmartAttend Agent",
        "Insufficient evidence to propose a safe correction.",
        ["Fallback"],
      );
      push(
        "08:17",
        "Escalated",
        "failure",
        "SmartAttend Agent",
        "Routed to HR Operations for manual review.",
        ["Escalated"],
      );
    }
  } else {
    push(
      "08:16",
      "AI proposal generated",
      "success",
      "SmartAttend Agent",
      `Confidence ${Math.round((s.confidence ?? 0.8) * 100)}%`,
    );
    push(
      "08:17",
      "Validation completed",
      failed ? "failure" : "success",
      "Validator Suite",
      failed ? `${s.fail!.length} check(s) failed — proposal blocked` : "All 5 checks passed",
    );
    if (s.status === "Escalated")
      push(
        "08:18",
        "Escalated",
        "failure",
        "SmartAttend Agent",
        "Blocked proposal escalated to HR Operations.",
        ["Escalated"],
      );
    if (s.status === "Approved") {
      push("10:42", "Manager approved", "success", "Rebecca Thorne", "Approved AI proposal.");
      push(
        "10:43",
        "Timecard updated",
        "success",
        "Timekeeping Backend",
        "Correction applied by backend after authorized approval.",
      );
    }
    if (s.status === "Rejected")
      push(
        "11:05",
        "Manager rejected",
        "failure",
        "Rebecca Thorne",
        "Employee confirmed different times; manual correction requested.",
      );
  }
  audits[id] = ev;
});

export const attendanceOverview = [
  { day: "Mon", present: 231, absent: 9, leave: 8 },
  { day: "Tue", present: 236, absent: 6, leave: 6 },
  { day: "Wed", present: 228, absent: 11, leave: 9 },
  { day: "Thu", present: 233, absent: 7, leave: 8 },
  { day: "Fri", present: 224, absent: 12, leave: 12 },
  { day: "Sat", present: 118, absent: 4, leave: 3 },
  { day: "Sun", present: 96, absent: 3, leave: 2 },
];

export const weeklyTrend = [
  { week: "W40", rate: 94.1, exceptions: 31 },
  { week: "W41", rate: 95.3, exceptions: 27 },
  { week: "W42", rate: 93.8, exceptions: 34 },
  { week: "W43", rate: 96.0, exceptions: 22 },
  { week: "W44", rate: 95.6, exceptions: 25 },
  { week: "W45", rate: 96.4, exceptions: 22 },
];
