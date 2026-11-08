import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { RotateCw, Search } from "lucide-react";
import { exceptionsQuery } from "@/lib/api/queries";
import type { ExceptionFilters } from "@/lib/api/types";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ErrorState, PageHeader, RowsSkeleton } from "@/components/app/states";
import { ExceptionsTable } from "@/components/app/exceptions-table";

export const Route = createFileRoute("/exceptions/")({
  validateSearch: (s: Record<string, unknown>): { q?: string | undefined } => ({ q: typeof s["q"] === "string" ? s["q"] : undefined }),
  head: () => ({
    meta: [
      { title: "Exception Queue – SmartAttend AI" },
      { name: "description", content: "Search, filter and review all detected attendance exceptions." },
      { property: "og:title", content: "Exception Queue – SmartAttend AI" },
      { property: "og:description", content: "Search, filter and review all detected attendance exceptions." },
    ],
  }),
  component: Queue,
});

function F({ value, onChange, label, options }: { value: string; onChange: (v: string) => void; label: string; options: string[] }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-9 w-full sm:w-48" aria-label={label}><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value="all">All {label.toLowerCase()}</SelectItem>
        {options.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

function Queue() {
  const { q } = Route.useSearch();
  const [search, setSearch] = useState(q ?? "");
  const [debounced, setDebounced] = useState(q ?? "");
  const [f, setF] = useState<ExceptionFilters>({ type: "all", status: "all", severity: "all" });
  useEffect(() => { setSearch(q ?? ""); setDebounced(q ?? ""); }, [q]);
  useEffect(() => { const t = setTimeout(() => setDebounced(search), 250); return () => clearTimeout(t); }, [search]);
  const { data, isLoading, error, refetch, isFetching } = useQuery({ ...exceptionsQuery({ ...f, search: debounced }), placeholderData: (p) => p });

  return (
    <>
      <PageHeader title="Exception Queue" description="All attendance exceptions detected by SmartAttend AI."
        actions={<Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}><RotateCw className={isFetching ? "size-4 animate-spin" : "size-4"} /> Refresh</Button>} />
      <div className="card-elevated overflow-hidden">
        <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:flex-wrap sm:items-center">
          <div className="relative flex-1 sm:min-w-64">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by employee name or ID" className="h-9 pl-9" />
          </div>
          <F label="Types" value={f.type!} onChange={(v) => setF({ ...f, type: v as never })} options={["Missing Punch", "Overtime Risk", "Schedule Conflict", "Meal Break Violation"]} />
          <F label="Statuses" value={f.status!} onChange={(v) => setF({ ...f, status: v as never })} options={["Pending Review", "AI Processing", "Awaiting Approval", "Approved", "Rejected", "Escalated"]} />
          <F label="Severities" value={f.severity!} onChange={(v) => setF({ ...f, severity: v as never })} options={["Low", "Medium", "High", "Critical"]} />
        </div>
        {error ? <div className="p-4"><ErrorState error={error} onRetry={refetch} /></div> : isLoading ? <RowsSkeleton /> : <ExceptionsTable rows={data!} />}
      </div>
    </>
  );
}
