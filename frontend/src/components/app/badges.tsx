import { cn } from "@/lib/utils";
import type { ExceptionStatus, Severity } from "@/lib/api/types";
import { CheckCircle2, XCircle } from "lucide-react";

const tone = {
  neutral: "bg-muted text-muted-foreground border-border",
  info: "bg-info-soft text-info border-info/20",
  warning: "bg-warning-soft text-warning border-warning/25",
  danger: "bg-danger-soft text-destructive border-destructive/20",
  success: "bg-success-soft text-success border-success/20",
  primary: "bg-primary text-primary-foreground border-primary",
} as const;
export type Tone = keyof typeof tone;

export function Pill({ t = "neutral", className, children, dot }: { t?: Tone; className?: string; children: React.ReactNode; dot?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium", tone[t], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

const statusTone: Record<ExceptionStatus, Tone> = {
  "Pending Review": "neutral",
  "AI Processing": "info",
  "Awaiting Approval": "warning",
  Approved: "success",
  Rejected: "danger",
  Escalated: "danger",
};
export const StatusBadge = ({ status }: { status: ExceptionStatus }) => (
  <Pill t={statusTone[status]} dot>
    {status}
  </Pill>
);

const sevTone: Record<Severity, Tone> = { Low: "neutral", Medium: "info", High: "warning", Critical: "danger" };
export const SeverityBadge = ({ severity }: { severity: Severity }) => <Pill t={sevTone[severity]}>{severity}</Pill>;

export function CheckBadge({ name, passed }: { name: string; passed: boolean }) {
  return (
    <div className={cn("flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm", passed ? "border-success/20 bg-success-soft" : "border-destructive/30 bg-danger-soft")}>
      <span className="flex items-center gap-2 font-medium text-foreground">
        {passed ? <CheckCircle2 className="size-4 text-success" /> : <XCircle className="size-4 text-destructive" />}
        {name}
      </span>
      <span className={cn("font-mono text-xs font-semibold", passed ? "text-success" : "text-destructive")}>{passed ? "PASS" : "FAIL"}</span>
    </div>
  );
}
