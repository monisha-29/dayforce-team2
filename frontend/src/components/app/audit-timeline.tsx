import { Link } from "@tanstack/react-router";
import { AlertOctagon, CheckCircle2, CircleDot, RotateCw, ShieldAlert, XCircle } from "lucide-react";
import type { AuditEvent } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { Pill } from "./badges";
import { EmptyState } from "./states";

const icon = { success: CheckCircle2, failure: XCircle, warning: RotateCw, info: CircleDot };
const color = { success: "text-success bg-success-soft", failure: "text-destructive bg-danger-soft", warning: "text-warning bg-warning-soft", info: "text-info bg-info-soft" };
const flagTone = { Retried: "warning", Fallback: "info", Escalated: "danger" } as const;
const flagIcon = { Retried: RotateCw, Fallback: ShieldAlert, Escalated: AlertOctagon };

export const fmtTs = (t: string) => new Date(t).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function AuditTimeline({ events, showException }: { events: AuditEvent[]; showException?: boolean }) {
  if (!events.length) return <EmptyState title="No audit events" />;
  return (
    <ol className="relative space-y-1">
      {events.map((e, i) => {
        const I = icon[e.status];
        return (
          <li key={e.id} className="relative flex gap-4 pb-4">
            {i < events.length - 1 && <span className="absolute left-4 top-9 bottom-0 w-px bg-border" />}
            <span className={cn("z-10 grid size-8 shrink-0 place-items-center rounded-full", color[e.status])}><I className="size-4" /></span>
            <div className="flex-1 rounded-lg border bg-card px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold">{e.action}</p>
                {e.flags.map((f) => { const F = flagIcon[f]; return <Pill key={f} t={flagTone[f]}><F className="size-3" />{f}</Pill>; })}
                {showException && <Link to="/exceptions/$id" params={{ id: e.exceptionId }} className="font-mono text-xs text-primary hover:underline">{e.exceptionId}</Link>}
                <span className="ml-auto text-xs text-muted-foreground">{fmtTs(e.timestamp)}</span>
              </div>
              {e.detail && <p className="mt-1 text-sm text-muted-foreground">{e.detail}</p>}
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>User: <span className="text-foreground">{e.user}</span></span>
                <span>Status: <span className="capitalize text-foreground">{e.status}</span></span>
                <span>Trace: <span className="font-mono text-foreground">{e.traceId}</span></span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
