import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { DecisionRequest, ExceptionFilters } from "./types";

export const exceptionsQuery = (filters: ExceptionFilters = {}) =>
  queryOptions({
    queryKey: ["exceptions", filters],
    queryFn: () => api.listExceptions(filters),
    staleTime: 30_000,
  });

export const exceptionQuery = (id: string) =>
  queryOptions({ queryKey: ["exception", id], queryFn: () => api.getException(id) });

export const auditQuery = (id: string) =>
  queryOptions({ queryKey: ["audit", id], queryFn: () => api.getAudit(id) });

export const allAuditQuery = () =>
  queryOptions({ queryKey: ["audit", "all"], queryFn: () => api.getAllAudit() });

export const attendanceQuery = (date?: string) =>
  queryOptions({
    queryKey: ["attendance", date ?? "latest"],
    queryFn: () => api.getAttendance(date),
    staleTime: 30_000,
  });

export const attendanceSummaryQuery = () =>
  queryOptions({
    queryKey: ["attendance", "summary"],
    queryFn: () => api.getAttendanceSummary(),
    staleTime: 30_000,
  });

function useInvalidateAll() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["exceptions"] }),
      qc.invalidateQueries({ queryKey: ["exception"] }),
      qc.invalidateQueries({ queryKey: ["audit"] }),
      qc.invalidateQueries({ queryKey: ["attendance"] }),
    ]);
}

export function useDecision(proposalId: string) {
  const inv = useInvalidateAll();
  return useMutation({
    mutationFn: (body: DecisionRequest) => api.submitDecision(proposalId, body),
    onSuccess: inv,
  });
}

export function useRegenerate(id: string) {
  const inv = useInvalidateAll();
  return useMutation({ mutationFn: () => api.requestProposal(id), onSuccess: inv });
}

export function useEscalate(id: string) {
  const inv = useInvalidateAll();
  return useMutation({ mutationFn: (note: string) => api.escalate(id, note), onSuccess: inv });
}
