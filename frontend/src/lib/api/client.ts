// API service layer. Set VITE_API_BASE_URL to point at the FastAPI backend and
// VITE_USE_MOCK_API=false to switch off the in-browser mock. The UI only calls
// these functions, so swapping mock -> real needs no UI changes.
import type {
  AttendanceException,
  AuditEvent,
  DecisionRequest,
  DecisionResponse,
  ExceptionDetail,
  ExceptionFilters,
  Proposal,
  Timecard,
} from "./types";
import { audits, computeHours, exceptions, proposals } from "./mock-data";

export const API_BASE_URL = (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://localhost:8000/api/v1";
export const USE_MOCK = (import.meta.env["VITE_USE_MOCK_API"] as string | undefined) !== "false";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.detail ?? msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status);
  }
  return res.json() as Promise<T>;
}

const delay = (ms = 450) => new Promise((r) => setTimeout(r, ms + Math.random() * 250));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const traceId = () => `tr-${Math.random().toString(16).slice(2, 8)}`;

function addAudit(exceptionId: string, e: Omit<AuditEvent, "id" | "exceptionId" | "timestamp" | "traceId">) {
  const list = (audits[exceptionId] ??= []);
  const t = traceId();
  list.push({ ...e, id: `${exceptionId}-${list.length}`, exceptionId, timestamp: new Date().toISOString(), traceId: t });
  return t;
}

/** Mirrors backend validator rules for edited timecards (mock only). */
export function validateEdited(tc: Timecard) {
  const errors: string[] = [];
  const re = /^([01]\d|2[0-3]):[0-5]\d$/;
  for (const k of ["checkIn", "checkOut"] as const) if (!tc[k] || !re.test(tc[k]!)) errors.push(`${k === "checkIn" ? "Check-in" : "Check-out"} must be a valid HH:MM time.`);
  for (const k of ["mealStart", "mealEnd"] as const) if (tc[k] && !re.test(tc[k]!)) errors.push(`Meal ${k === "mealStart" ? "start" : "end"} must be HH:MM.`);
  const h = computeHours(tc);
  if (h !== null && (h <= 0 || h > 16)) errors.push("Total worked hours must be between 0 and 16.");
  return { errors, hours: h };
}

export const api = {
  async listExceptions(filters: ExceptionFilters = {}): Promise<AttendanceException[]> {
    if (!USE_MOCK) {
      const q = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => v && v !== "all" && q.set(k, String(v)));
      return http(`/exceptions?${q}`);
    }
    await delay();
    const s = filters.search?.toLowerCase().trim();
    return clone(
      exceptions.filter(
        (e) =>
          (!s || e.employee.name.toLowerCase().includes(s) || e.employee.id.toLowerCase().includes(s) || e.id.toLowerCase().includes(s)) &&
          (!filters.type || filters.type === "all" || e.type === filters.type) &&
          (!filters.status || filters.status === "all" || e.status === filters.status) &&
          (!filters.severity || filters.severity === "all" || e.severity === filters.severity),
      ),
    );
  },

  async getException(id: string): Promise<ExceptionDetail> {
    if (!USE_MOCK) return http(`/exceptions/${id}`);
    await delay();
    const e = exceptions.find((x) => x.id === id);
    if (!e) throw new ApiError(`Exception ${id} not found`, 404);
    return clone({ ...e, proposal: (e.proposalId && proposals[e.proposalId]) || null });
  },

  /** Ask the agent to (re)generate a proposal. */
  async requestProposal(id: string): Promise<Proposal | null> {
    if (!USE_MOCK) return http(`/exceptions/${id}/proposal`, { method: "POST" });
    await delay(900);
    const e = exceptions.find((x) => x.id === id);
    if (!e) throw new ApiError("Not found", 404);
    addAudit(id, { action: "Retry attempted", user: "Rebecca Thorne", status: "warning", detail: "Manager requested proposal regeneration.", flags: ["Retried"] });
    if (!e.proposalId) {
      addAudit(id, { action: "Fallback triggered", user: "SmartAttend Agent", status: "warning", detail: "Still insufficient evidence; no proposal produced.", flags: ["Fallback"] });
      return null;
    }
    return clone(proposals[e.proposalId] ?? null);
  },

  async escalate(id: string, note: string): Promise<DecisionResponse> {
    if (!USE_MOCK) return http(`/exceptions/${id}/escalate`, { method: "POST", body: JSON.stringify({ note }) });
    await delay();
    const e = exceptions.find((x) => x.id === id);
    if (!e) throw new ApiError("Not found", 404);
    e.status = "Escalated";
    const t = addAudit(id, { action: "Escalated", user: "Rebecca Thorne", status: "failure", detail: note || "Escalated to HR Operations.", flags: ["Escalated"] });
    return { exceptionId: id, newStatus: "Escalated", message: "Escalated to HR Operations.", traceId: t };
  },

  async submitDecision(proposalId: string, body: DecisionRequest): Promise<DecisionResponse> {
    if (!USE_MOCK) return http(`/proposals/${proposalId}/decision`, { method: "POST", body: JSON.stringify(body) });
    await delay(800);
    const p = proposals[proposalId];
    if (!p) throw new ApiError("Proposal not found", 404);
    const e = exceptions.find((x) => x.id === p.exceptionId)!;
    if (["Approved", "Rejected"].includes(e.status)) throw new ApiError(`Exception already ${e.status.toLowerCase()}.`, 409);

    if (body.decision === "reject") {
      if (!body.reason?.trim()) throw new ApiError("A rejection reason is required.", 422);
      e.status = "Rejected";
      const t = addAudit(e.id, { action: "Manager rejected", user: "Rebecca Thorne", status: "failure", detail: body.reason, flags: [] });
      return { exceptionId: e.id, newStatus: "Rejected", message: "Rejection recorded. Timecard unchanged.", traceId: t };
    }
    if (body.decision === "approve") {
      if (p.blocked) throw new ApiError("Proposal is blocked by failed validation and cannot be approved as-is.", 422);
      e.status = "Approved";
      addAudit(e.id, { action: "Manager approved", user: "Rebecca Thorne", status: "success", detail: "Approved AI proposal.", flags: [] });
      const t = addAudit(e.id, { action: "Timecard updated", user: "Timekeeping Backend (mock)", status: "success", detail: "Simulated: backend would apply the correction.", flags: [] });
      return { exceptionId: e.id, newStatus: "Approved", message: "Approval accepted by backend (mock).", traceId: t };
    }
    // edit
    const tc = body.editedTimecard!;
    const { errors, hours } = validateEdited(tc);
    if (errors.length) throw new ApiError(`Backend validation failed: ${errors.join(" ")}`, 422);
    p.proposed = { ...tc, totalHours: hours };
    p.blocked = false;
    p.validators = p.validators.map((v) => ({ name: v.name, passed: true }));
    e.status = "Approved";
    addAudit(e.id, { action: "Manager edited", user: "Rebecca Thorne", status: "info", detail: "Edited proposal submitted for validation.", flags: [] });
    addAudit(e.id, { action: "Validation completed", user: "Validator Suite", status: "success", detail: "Edited proposal passed all checks.", flags: [] });
    const t = addAudit(e.id, { action: "Timecard updated", user: "Timekeeping Backend (mock)", status: "success", detail: "Simulated: backend would apply the edited correction.", flags: [] });
    return { exceptionId: e.id, newStatus: "Approved", message: "Edited proposal validated and approved (mock).", traceId: t };
  },

  async getAudit(id: string): Promise<AuditEvent[]> {
    if (!USE_MOCK) return http(`/exceptions/${id}/audit`);
    await delay();
    return clone(audits[id] ?? []);
  },

  async getAllAudit(): Promise<AuditEvent[]> {
    if (!USE_MOCK) return http(`/audit`);
    await delay();
    return clone(Object.values(audits).flat()).sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  },
};
