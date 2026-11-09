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
  CircleAlert,
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
import type { ExceptionDetail, Proposal, Timecard } from "@/lib/api/types";
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

      <Card title="Employee information">
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

      {!p ? (
        <NoProposal e={e} />
      ) : (
        <>
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <Card title="Original timecard" icon={Lock}>
              <TimecardList tc={e.original} />
            </Card>
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
              <TimecardList tc={p.proposed} original={e.original} changed={p.changedFields} />
            </Card>
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
  return (
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
  const busy = m.isPending || esc.isPending;
  const { errors, hours } = validateEdited(edit);

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
          <div className="grid grid-cols-3 gap-2">
            <Button
              onClick={() => open("approve")}
              disabled={busy || p.blocked}
              title={p.blocked ? "Blocked by failed validation" : undefined}
              className="bg-success text-primary-foreground hover:bg-success/90"
            >
              <Check className="size-4" />
              Approve
            </Button>
            <Button variant="outline" onClick={() => open("edit")} disabled={busy}>
              <Pencil className="size-4" />
              Edit
            </Button>
            <Button
              variant="outline"
              onClick={() => open("reject")}
              disabled={busy}
              className="border-destructive/40 text-destructive hover:bg-danger-soft hover:text-destructive"
            >
              <X className="size-4" />
              Reject
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
          <p className="text-xs text-muted-foreground">
            Decisions are sent to the backend. This screen never edits a timecard directly.
          </p>
        </div>
      )}

      <Dialog open={dlg === "approve"} onOpenChange={(o) => !busy && !o && setDlg(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve AI proposal?</DialogTitle>
            <DialogDescription>
              Your approval will be submitted to the backend for {e.employee.name} ({e.id}). The
              timecard is only updated by the backend after it accepts your authorized approval —
              the status here changes only after a successful response.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDlg(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => submit({ decision: "approve" })} disabled={busy}>
              {m.isPending && <Loader2 className="size-4 animate-spin" />}Confirm approval
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dlg === "reject"} onOpenChange={(o) => !busy && !o && setDlg(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject proposal</DialogTitle>
            <DialogDescription>
              Provide a reason. It will be recorded in the audit trail.
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
  const processing = e.status === "AI Processing";
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
          {processing ? "AI is analyzing this exception" : "AI proposal unavailable"}
        </p>
        <p className="max-w-sm text-sm text-muted-foreground">
          {processing
            ? "A correction proposal is being generated and validated. Check back shortly."
            : "The agent could not produce a safe correction with the available evidence. Retry generation or escalate for manual handling."}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
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
            Retry generation
          </Button>
          {e.status !== "Escalated" && (
            <Button
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
