import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import {
  AlertOctagon,
  ArrowLeft,
  BookOpen,
  Bot,
  Check,
  CalendarDays,
  CircleAlert,
  Clock,
  Loader2,
  Lock,
  Pencil,
  RotateCw,
  Sparkles,
  X,
} from "lucide-react";
import {
  auditQuery,
  exceptionQuery,
  useDecision,
  useEscalate,
  useRegenerate,
} from "@/lib/api/queries";
import { validateEdited } from "@/lib/api/client";
import type { ExceptionDetail, Proposal, PunchKind, Timecard } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CheckBadge, Pill, SeverityBadge, StatusBadge } from "@/components/app/badges";
import { ErrorState } from "@/components/app/states";
import { AuditTimeline } from "@/components/app/audit-timeline";
import { fmtDate } from "@/components/app/exceptions-table";

export const Route = createFileRoute("/exceptions/$id")({
  head: ({ params }) => ({
    meta: [
      { title: `Review ${params.id} – SmartAttend AI` },
      {
        name: "description",
        content: "Compare original and AI-proposed timecards, review validation and decide.",
      },
      { property: "og:title", content: `Review ${params.id} – SmartAttend AI` },
      {
        property: "og:description",
        content: "Compare original and AI-proposed timecards, review validation and decide.",
      },
    ],
  }),
  component: Review,
});

const fields: { k: keyof Timecard; label: string }[] = [
  { k: "checkIn", label: "Check-in" },
  { k: "checkOut", label: "Check-out" },
  { k: "mealStart", label: "Meal start" },
  { k: "mealEnd", label: "Meal end" },
  { k: "totalHours", label: "Total hours" },
];
const to12 = (t: string) => {
  const [h = 0, m = 0] = t.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};
const show = (k: keyof Timecard, v: Timecard[keyof Timecard]) =>
  v === null || v === undefined
    ? k === "totalHours"
      ? "Incomplete"
      : "Missing"
    : k === "totalHours"
      ? `${v} hrs`
      : to12(String(v));

function Card({
  title,
  icon: I,
  children,
  className,
}: {
  title: string;
  icon?: typeof Bot;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("card-elevated", className)}>
      <div className="flex items-center gap-2 border-b px-5 py-3.5">
        {I && <I className="size-4 text-primary" />}
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Review() {
  const { id } = Route.useParams();
  const { data, isLoading, error, refetch } = useQuery(exceptionQuery(id));
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (isLoading || !data)
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-32" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  return <ReviewBody e={data} />;
}

const PUNCH_LABEL: Record<PunchKind, string> = {
  IN: "Clock in",
  OUT: "Clock out",
  BREAK_START: "Meal start",
  BREAK_END: "Meal end",
};

/** What the detector found, in words: visible before any proposal exists. */
export function DetectedIssueCard({ e }: { e: ExceptionDetail }) {
  if (!e.detectedIssue) return null;
  return (
    <section
      data-testid="detected-issue"
      className="mb-6 flex items-start gap-3 rounded-xl border border-warning/40 bg-warning-soft p-4"
    >
      <CircleAlert className="mt-0.5 size-5 shrink-0 text-warning" />
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-warning">
          What was detected
        </p>
        <p className="mt-1 text-sm font-medium text-foreground">{e.detectedIssue}</p>
      </div>
    </section>
  );
}

/** Rest-period and consecutive-days exceptions span several days; show those days. */
export function RelatedShiftsCard({ e }: { e: ExceptionDetail }) {
  if (!e.contextShifts || e.contextShifts.length === 0) return null;
  return (
    <Card title="Shifts behind this exception" icon={CalendarDays} className="mt-6">
      {e.contextSummary && (
        <p className="mb-3 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-sm font-medium text-warning">
          {e.contextSummary}
        </p>
      )}
      <table className="w-full text-sm" data-testid="related-shifts">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="pb-2 font-medium">Date</th>
            <th className="pb-2 font-medium">Clock in</th>
            <th className="pb-2 font-medium">Clock out</th>
          </tr>
        </thead>
        <tbody>
          {e.contextShifts.map((s) => (
            <tr
              key={s.date}
              className={cn("border-t", s.date === e.date && "bg-muted/60 font-medium")}
            >
              <td className="py-2 pr-4">
                {fmtDate(s.date)}
                {s.date === e.date && (
                  <span className="ml-2 text-xs text-muted-foreground">this exception</span>
                )}
              </td>
              <td className="py-2 pr-4 font-mono">{to12(s.start)}</td>
              <td className="py-2 font-mono">
                {s.end ? to12(s.end) : "Missing"}
                {s.endDate && (
                  <span className="ml-2 text-xs text-muted-foreground">{fmtDate(s.endDate)}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/** The raw punches behind the exception: the timecard below hides repeats and gaps. */
export function PunchesCard({ e }: { e: ExceptionDetail }) {
  if (!e.punches || e.punches.length === 0) return null;
  return (
    <Card title="Recorded punches" icon={Clock} className="mt-6">
      {e.schedule && (
        <p className="mb-3 text-xs text-muted-foreground">
          Assigned schedule {to12(e.schedule.start)}–{to12(e.schedule.end)}
        </p>
      )}
      <table className="w-full text-sm" data-testid="punch-table">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="pb-2 font-medium">Time</th>
            <th className="pb-2 font-medium">Punch</th>
            <th className="pb-2 font-medium">Source</th>
            <th className="pb-2 font-medium">Note</th>
          </tr>
        </thead>
        <tbody>
          {e.punches.map((p) => (
            <tr
              key={p.id}
              className={cn("border-t", p.isDuplicate && "bg-warning-soft")}
              data-duplicate={p.isDuplicate || undefined}
            >
              <td className="py-2 pr-4 font-mono">
                {to12(p.time)}
                {p.date !== e.date && (
                  <span className="ml-2 text-xs text-muted-foreground">{fmtDate(p.date)}</span>
                )}
              </td>
              <td className="py-2 pr-4">
                {PUNCH_LABEL[p.type]}
                {p.isDuplicate && (
                  <Pill t="warning" className="ml-2">
                    Duplicate
                  </Pill>
                )}
              </td>
              <td className="py-2 pr-4 text-muted-foreground">{p.source}</td>
              <td className="py-2 text-muted-foreground">{p.notes ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/** What the manager's buttons mean when the exception has no time fix. */
export const DECISION_COPY: Record<
  string,
  {
    authorize: string;
    authorizeShort: string;
    authorizeHelp: string;
    decline: string;
    declineHelp: string;
  }
> = {
  "Consecutive Days": {
    authorize: "Authorize the extra day",
    authorizeShort: "Authorize",
    authorizeHelp:
      "The extra day was needed or agreed. The times stay as recorded and your note is kept in the audit trail.",
    decline: "Don't authorize",
    declineHelp:
      "The day should not have been worked or scheduled. Record why; HR or scheduling follows up outside this system.",
  },
  "Rest Period Violation": {
    authorize: "Accept the short rest",
    authorizeShort: "Accept",
    authorizeHelp:
      "The short rest was a schedule change or a voluntary swap. The times stay as recorded.",
    decline: "Not acceptable",
    declineHelp: "Record why, so scheduling can correct the pattern.",
  },
  "Duplicate Punch": {
    authorize: "Confirm the duplicate",
    authorizeShort: "Confirm",
    authorizeHelp:
      "The repeat was a double tap. Hours already use the first punch, so nothing changes.",
    decline: "Not a duplicate",
    declineHelp: "Record what actually happened.",
  },
  "Overtime Risk": {
    authorize: "Authorize the overtime",
    authorizeShort: "Authorize",
    authorizeHelp: "The hours were worked and approved. The times stay as recorded.",
    decline: "Don't authorize",
    declineHelp: "Record why the overtime was not approved.",
  },
  "Schedule Conflict": {
    authorizeShort: "Excuse",
    authorize: "Excuse the deviation",
    authorizeHelp: "The punches stand and the deviation from the schedule is accepted.",
    decline: "Don't excuse",
    declineHelp: "Record why the deviation is not accepted.",
  },
};

/** Exceptions with no time fix: the AI's useful output is a recommended decision, not a timecard. */
export function RecommendedDecisionCard({ e, p }: { e: ExceptionDetail; p: Proposal }) {
  const copy = DECISION_COPY[e.type];
  return (
    <Card title="Recommended decision" icon={Sparkles} className="ring-1 ring-warning/30">
      <div data-testid="recommended-decision" className="space-y-4 text-sm">
        <div className="rounded-lg border border-border bg-muted px-3 py-2 text-xs font-medium text-muted-foreground">
          <CircleAlert className="mr-1.5 inline size-4" />
          The recorded times are correct, so no timecard change is proposed. This needs a decision,
          not an edit.
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">AI recommendation</p>
          <p className="mt-1 font-medium">{p.recommendation}</p>
        </div>
        {!copy && p.blocked && (
          <p className="text-muted-foreground">
            This cannot be approved as it stands. Use “Edit times” to record what you verified (for
            example the meal break that was taken), reject with a reason, or escalate.
          </p>
        )}
        {copy && (
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Your options</p>
            <ul className="mt-2 space-y-2">
              <li>
                <span className="font-medium">{copy.authorize}:</span> {copy.authorizeHelp}
              </li>
              <li>
                <span className="font-medium">{copy.decline}:</span> {copy.declineHelp}
              </li>
              <li>
                <span className="font-medium">Escalate to HR:</span> You are not sure, or someone
                else must decide.
              </li>
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function ReviewBody({ e }: { e: ExceptionDetail }) {
  const p = e.proposal;
  const decided = e.status === "Approved" || e.status === "Rejected";
  return (
    <>
      <Link
        to="/exceptions"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Exception queue
      </Link>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{e.type}</h1>
        <span className="font-mono text-sm text-muted-foreground">{e.id}</span>
        <SeverityBadge severity={e.severity} />
        <StatusBadge status={e.status} />
      </div>

      <DetectedIssueCard e={e} />
      <RelatedShiftsCard e={e} />

      <Card title="Employee information" className={e.contextShifts?.length ? "mt-6" : ""}>
        <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-5">
          {[
            ["Employee", e.employee.name],
            ["Employee ID", e.employee.id],
            ["Department", e.employee.department],
            [
              "Assigned shift",
              `${e.employee.shift} · ${to12(e.employee.shiftStart)}–${to12(e.employee.shiftEnd)}`,
            ],
            ["Attendance date", fmtDate(e.date)],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt>
              <dd className="mt-1 font-medium">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <PunchesCard e={e} />

      {!p ? (
        <NoProposal e={e} />
      ) : (
        <>
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Card title="Original timecard" icon={Lock}>
              <TimecardList tc={e.original} />
            </Card>
            {p.changedFields.length === 0 ? (
              <RecommendedDecisionCard e={e} p={p} />
            ) : (
              <Card
                title="AI-proposed timecard"
                icon={Sparkles}
                className={e.status === "Approved" ? "" : "ring-1 ring-warning/30"}
              >
                {e.status !== "Approved" && (
                  <div className="mb-4 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-xs font-medium text-warning">
                    <CircleAlert className="size-4" /> Suggested values — UNAPPROVED until a manager
                    approves them.
                  </div>
                )}
                {e.status !== "Approved" && !p.blocked && p.changedFields.length === 0 && (
                  <div
                    data-testid="no-change-notice"
                    className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2 text-xs font-medium text-muted-foreground"
                  >
                    <CircleAlert className="size-4 shrink-0" />
                    <span>
                      <strong>No time change proposed.</strong> The recorded times stand and a
                      manager decision is needed. {p.recommendation}
                    </span>
                  </div>
                )}
                <TimecardList tc={p.proposed} original={e.original} changed={p.changedFields} />
              </Card>
            )}
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              <Explanation p={p} />
            </div>
            <div className="space-y-6">
              <Validators p={p} />
              <Decision e={e} p={p} decided={decided} />
            </div>
          </div>
        </>
      )}

      <AuditCard id={e.id} />
    </>
  );
}

function TimecardList({
  tc,
  original,
  changed = [],
}: {
  tc: Timecard;
  original?: Timecard;
  changed?: (keyof Timecard)[];
}) {
  const noMeal =
    !!tc.checkIn && !!tc.checkOut && !tc.mealStart && !tc.mealEnd && (tc.totalHours ?? 0) >= 5;
  return (
    <>
      <dl className="divide-y">
        {fields.map(({ k, label }) => {
          const isChanged = changed.includes(k);
          const missing = tc[k] === null;
          return (
            <div
              key={k}
              className={cn(
                "flex items-center justify-between rounded-md px-2 py-2.5 text-sm",
                isChanged && "bg-highlight",
              )}
            >
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="flex items-center gap-2">
                {isChanged && original && (
                  <span className="text-xs text-muted-foreground line-through">
                    {show(k, original[k])}
                  </span>
                )}
                <span
                  className={cn(
                    "font-mono font-medium",
                    missing && "text-destructive",
                    isChanged && "text-primary",
                  )}
                >
                  {show(k, tc[k])}
                </span>
                {isChanged && (
                  <Pill t="warning" className="px-1.5 py-0 text-[10px]">
                    Changed
                  </Pill>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
      {noMeal && (
        <p data-testid="no-meal-note" className="mt-2 px-2 text-xs text-muted-foreground">
          No meal break is recorded, so no break time is deducted from the total.
        </p>
      )}
    </>
  );
}

function Explanation({ p }: { p: Proposal }) {
  const pct = Math.round(p.confidence * 100);
  const level =
    pct >= 85 ? ["High", "success"] : pct >= 65 ? ["Moderate", "warning"] : ["Low", "danger"];
  return (
    <Card title="AI explanation & recommendation" icon={Bot}>
      <div className="space-y-5 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Detected issue</p>
          <p className="mt-1 font-medium">{p.detectedIssue}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Reason for exception
          </p>
          <p className="mt-1 leading-relaxed">{p.reason}</p>
        </div>
        <div className="rounded-lg border bg-muted/40 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <BookOpen className="size-4 text-primary" />
            <p className="font-medium">{p.policyTitle}</p>
            <Pill t="primary" className="font-mono">
              {p.policyClauseId}
            </Pill>
          </div>
          <blockquote className="mt-2 border-l-2 border-primary/40 pl-3 text-muted-foreground italic">
            {p.policyExcerpt}
          </blockquote>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">AI recommendation</p>
          <p className="mt-1 font-medium">{p.recommendation}</p>
        </div>
        <div>
          <div className="flex items-center justify-between">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Confidence</p>
            <Pill t={level[1] as "success"}>
              {level[0]} · {pct}%
            </Pill>
          </div>
          <Progress value={pct} className="mt-2 h-2" />
        </div>
        {p.missingInformation.length > 0 && (
          <div className="rounded-lg border border-warning/30 bg-warning-soft p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-warning">
              Missing information
            </p>
            <ul className="mt-1 list-disc pl-5 text-foreground">
              {p.missingInformation.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function Validators({ p }: { p: Proposal }) {
  const failed = p.validators.filter((v) => !v.passed);
  return (
    <Card title="Validator results">
      {p.blocked && (
        <div className="mb-4 rounded-lg border border-destructive/40 bg-danger-soft p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-destructive">
            <AlertOctagon className="size-4" />
            Proposal blocked — cannot be approved as-is
          </p>
          <ul className="mt-2 space-y-1.5 text-destructive">
            {failed.map((v) => (
              <li key={v.name}>
                <span className="font-medium">{v.name}:</span> {v.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="space-y-2">
        {p.validators.map((v) => (
          <CheckBadge key={v.name} name={v.name} passed={v.passed} />
        ))}
      </div>
    </Card>
  );
}

function Decision({ e, p, decided }: { e: ExceptionDetail; p: Proposal; decided: boolean }) {
  const [dlg, setDlg] = useState<null | "approve" | "edit" | "reject" | "escalate">(null);
  const [reason, setReason] = useState("");
  const [edit, setEdit] = useState<Timecard>(p.proposed);
  const [step, setStep] = useState<"form" | "preview">("form");
  const m = useDecision(p.id);
  const esc = useEscalate(e.id);
  const regen = useRegenerate(e.id);
  const busy = m.isPending || esc.isPending || regen.isPending;
  const { errors, hours } = validateEdited(edit);
  const copy = p.changedFields.length === 0 ? DECISION_COPY[e.type] : undefined;

  const submit = (body: Parameters<typeof m.mutate>[0]) =>
    m.mutate(body, {
      onSuccess: (r) => {
        toast.success(r.message, { description: `Trace ${r.traceId}` });
        setDlg(null);
      },
      onError: (err) => toast.error("Submission failed", { description: err.message }),
    });

  const open = (d: typeof dlg) => {
    m.reset();
    setReason("");
    setEdit(p.proposed);
    setStep("form");
    setDlg(d);
  };

  return (
    <Card title="Manager decision">
      {decided ? (
        <p className="text-sm text-muted-foreground">
          This exception was{" "}
          <span className="font-medium text-foreground">{e.status.toLowerCase()}</span>. No further
          action required.
        </p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2 [&>button]:h-auto [&>button]:min-h-9 [&>button]:whitespace-normal [&>button]:py-2 [&>button]:leading-tight">
            <Button
              onClick={() => open("approve")}
              disabled={busy || p.blocked}
              title={p.blocked ? "Blocked by failed validation" : undefined}
              className="bg-success text-primary-foreground hover:bg-success/90"
            >
              <Check className="size-4" />
              {copy ? copy.authorizeShort : "Approve"}
            </Button>
            <Button variant="outline" onClick={() => open("edit")} disabled={busy}>
              <Pencil className="size-4" />
              Edit times
            </Button>
            <Button
              variant="outline"
              onClick={() => open("reject")}
              disabled={busy}
              className="border-destructive/40 text-destructive hover:bg-danger-soft hover:text-destructive"
            >
              <X className="size-4" />
              {copy ? copy.decline : "Reject"}
            </Button>
          </div>
          {p.blocked && (
            <p className="text-xs text-destructive">
              Approve is disabled: fix the values with Edit, reject, or escalate.
            </p>
          )}
          {e.status !== "Escalated" && (
            <Button
              variant="ghost"
              size="sm"
              className="w-full"
              onClick={() => open("escalate")}
              disabled={busy}
            >
              <AlertOctagon className="size-4" />
              Escalate to HR Operations
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="w-full"
            data-testid="regenerate-proposal"
            onClick={() =>
              regen.mutate(undefined, {
                onSuccess: () => toast.success("New proposal generated"),
                onError: (err) =>
                  toast.error("Could not generate a proposal", { description: err.message }),
              })
            }
            disabled={busy}
          >
            {regen.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RotateCw className="size-4" />
            )}
            {regen.isPending ? "Generating… this can take a minute or two" : "Regenerate proposal"}
          </Button>
          <p className="text-xs text-muted-foreground">
            Decisions are sent to the backend. This screen never edits a timecard directly.
          </p>
        </div>
      )}

      <Dialog open={dlg === "approve"} onOpenChange={(o) => !busy && !o && setDlg(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy ? `${copy.authorize}?` : "Approve AI proposal?"}</DialogTitle>
            <DialogDescription>
              {copy
                ? `${copy.authorizeHelp} This will be recorded for ${e.employee.name} (${e.id}).`
                : `Your approval will be submitted to the backend for ${e.employee.name} (${e.id}). The timecard is only updated by the backend after it accepts your authorized approval — the status here changes only after a successful response.`}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={reason}
            onChange={(ev) => setReason(ev.target.value)}
            placeholder="Optional note for the audit trail"
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDlg(null)} disabled={busy}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                submit(
                  reason.trim()
                    ? { decision: "approve", reason: reason.trim() }
                    : { decision: "approve" },
                )
              }
              disabled={busy}
            >
              {m.isPending && <Loader2 className="size-4 animate-spin" />}
              {copy ? "Confirm" : "Confirm approval"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dlg === "reject"} onOpenChange={(o) => !busy && !o && setDlg(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy ? copy.decline : "Reject proposal"}</DialogTitle>
            <DialogDescription>
              {copy ? `${copy.declineHelp} ` : ""}Provide a reason. It will be recorded in the audit
              trail.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={reason}
            onChange={(ev) => setReason(ev.target.value)}
            placeholder="e.g. Employee confirmed they left at 17:30; supervisor to submit manual correction."
            rows={4}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDlg(null)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => submit({ decision: "reject", reason })}
              disabled={busy || reason.trim().length < 5}
            >
              {m.isPending && <Loader2 className="size-4 animate-spin" />}Submit rejection
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dlg === "escalate"} onOpenChange={(o) => !busy && !o && setDlg(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Escalate to HR Operations</DialogTitle>
            <DialogDescription>Hand off this case for manual review.</DialogDescription>
          </DialogHeader>
          <Textarea
            value={reason}
            onChange={(ev) => setReason(ev.target.value)}
            placeholder="Optional note"
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDlg(null)} disabled={busy}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                esc.mutate(reason, {
                  onSuccess: (r) => {
                    toast.success(r.message);
                    setDlg(null);
                  },
                  onError: (err) => toast.error(err.message),
                })
              }
              disabled={busy}
            >
              {esc.isPending && <Loader2 className="size-4 animate-spin" />}Escalate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dlg === "edit"} onOpenChange={(o) => !busy && !o && setDlg(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {step === "form" ? "Edit proposed timecard" : "Review changes"}
            </DialogTitle>
            <DialogDescription>
              {step === "form"
                ? "Adjust values (24h HH:MM). The edited proposal will be re-validated by the backend before approval."
                : "Confirm the changes below. They will be submitted for backend validation and approval."}
            </DialogDescription>
          </DialogHeader>
          {step === "form" ? (
            <div className="grid grid-cols-2 gap-3">
              {fields
                .filter((f) => f.k !== "totalHours")
                .map(({ k, label }) => (
                  <div key={k} className="space-y-1.5">
                    <Label htmlFor={k}>{label}</Label>
                    <Input
                      id={k}
                      className="font-mono"
                      placeholder="HH:MM"
                      value={(edit[k] as string) ?? ""}
                      onChange={(ev) => setEdit({ ...edit, [k]: ev.target.value || null })}
                    />
                  </div>
                ))}
              {!edit.mealStart && !edit.mealEnd && (
                <p className="col-span-2 text-xs text-muted-foreground">
                  Meal times are never filled in automatically. Enter the break only if the employee
                  confirms they took one.
                </p>
              )}
              <div className="col-span-2 rounded-md bg-muted px-3 py-2 text-sm">
                Calculated hours: <span className="font-mono font-medium">{hours ?? "—"}</span>
              </div>
              {errors.length > 0 && (
                <ul className="col-span-2 space-y-1 text-xs text-destructive">
                  {errors.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="divide-y rounded-lg border text-sm">
              {fields.map(({ k, label }) => {
                const before = p.proposed[k];
                const after = k === "totalHours" ? hours : edit[k];
                const diff = before !== after;
                return (
                  <div
                    key={k}
                    className={cn("flex justify-between px-3 py-2", diff && "bg-highlight")}
                  >
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-mono">
                      {diff && (
                        <span className="mr-2 text-muted-foreground line-through">
                          {show(k, before)}
                        </span>
                      )}
                      <span className={diff ? "font-semibold text-primary" : ""}>
                        {show(k, after)}
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          {m.error && (
            <p className="rounded-md bg-danger-soft p-2 text-sm text-destructive">
              {m.error.message}
            </p>
          )}
          <DialogFooter>
            {step === "form" ? (
              <>
                <Button variant="outline" onClick={() => setDlg(null)}>
                  Cancel
                </Button>
                <Button onClick={() => setStep("preview")} disabled={errors.length > 0}>
                  Preview changes
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => setStep("form")} disabled={busy}>
                  Back
                </Button>
                <Button
                  onClick={() => submit({ decision: "edit", editedTimecard: edit })}
                  disabled={busy}
                >
                  {m.isPending && <Loader2 className="size-4 animate-spin" />}Submit for validation
                  & approval
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function NoProposal({ e }: { e: ExceptionDetail }) {
  const regen = useRegenerate(e.id);
  const esc = useEscalate(e.id);
  const processing = e.status === "AI Processing" || regen.isPending;
  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-2">
      <Card title="Original timecard" icon={Lock}>
        <TimecardList tc={e.original} />
      </Card>
      <section className="card-elevated flex flex-col items-center justify-center gap-3 p-8 text-center">
        <div className={cn("rounded-full p-3", processing ? "bg-info-soft" : "bg-warning-soft")}>
          {processing ? (
            <Loader2 className="size-6 animate-spin text-info" />
          ) : (
            <Bot className="size-6 text-warning" />
          )}
        </div>
        <p className="font-semibold">
          {processing ? "AI is analyzing this exception" : "Generate an AI proposal"}
        </p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {processing
            ? "A policy-grounded proposal is being generated and validated. A local model is used, so this can take a minute or two."
            : "No proposal has been generated yet. Click “Generate proposal” and the AI will draft a policy-grounded correction for you to review. This can take a minute or two."}
        </p>
        <div className="flex gap-2">
          <Button
            size="lg"
            disabled={regen.isPending}
            onClick={() =>
              regen.mutate(undefined, {
                onSuccess: (r) =>
                  r
                    ? toast.success("Proposal generated")
                    : toast.warning("Still no proposal available", {
                        description: "Fallback triggered — consider escalating.",
                      }),
                onError: (er) => toast.error(er.message),
              })
            }
          >
            {regen.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RotateCw className="size-4" />
            )}
            Generate proposal
          </Button>
          {e.status !== "Escalated" && (
            <Button
              variant="outline"
              size="lg"
              disabled={esc.isPending}
              onClick={() =>
                esc.mutate("No AI proposal available.", {
                  onSuccess: (r) => toast.success(r.message),
                  onError: (er) => toast.error(er.message),
                })
              }
            >
              {esc.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <AlertOctagon className="size-4" />
              )}
              Escalate
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}

function AuditCard({ id }: { id: string }) {
  const { data, isLoading, error, refetch } = useQuery(auditQuery(id));
  return (
    <Card title="Audit history" className="mt-6">
      {error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : isLoading ? (
        <Skeleton className="h-40" />
      ) : (
        <AuditTimeline events={data!} />
      )}
    </Card>
  );
}
