import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="card-elevated flex flex-col items-center gap-3 p-10 text-center">
      <div className="rounded-full bg-danger-soft p-3"><AlertTriangle className="size-5 text-destructive" /></div>
      <div>
        <p className="font-semibold">Couldn't load data</p>
        <p className="mt-1 text-sm text-muted-foreground">{error instanceof Error ? error.message : "Unexpected API error."}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}><RotateCw className="size-4" /> Retry</Button>
      )}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 p-12 text-center">
      <Inbox className="size-8 text-muted-foreground/60" />
      <p className="font-medium">{title}</p>
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function RowsSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
