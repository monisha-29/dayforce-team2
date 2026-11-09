import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Eye } from "lucide-react";
import type { AttendanceException } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SeverityBadge, StatusBadge } from "./badges";
import { EmptyState } from "./states";

type Key = "id" | "name" | "empId" | "department" | "type" | "date" | "severity" | "status";
const sevRank = { Low: 0, Medium: 1, High: 2, Critical: 3 };
const get = (e: AttendanceException, k: Key): string | number =>
  k === "name" ? e.employee.name : k === "empId" ? e.employee.id : k === "department" ? e.employee.department : k === "severity" ? sevRank[e.severity] : e[k];

export const fmtDate = (d: string) => new Date(d + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

export function ExceptionsTable({ rows, pageSize = 10, compact }: { rows: AttendanceException[]; pageSize?: number; compact?: boolean | undefined }) {
  const [sort, setSort] = useState<{ k: Key; dir: 1 | -1 }>({ k: "date", dir: -1 });
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => [...rows].sort((a, b) => {
    const x = get(a, sort.k), y = get(b, sort.k);
    return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
  }), [rows, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const p = Math.min(page, pages - 1);
  const view = sorted.slice(p * pageSize, p * pageSize + pageSize);

  const cols: { k: Key; label: string; hide?: boolean | undefined }[] = [
    { k: "id", label: "Exception ID" }, { k: "name", label: "Employee" }, { k: "empId", label: "Employee ID", hide: compact },
    { k: "department", label: "Department", hide: compact }, { k: "type", label: "Exception Type" }, { k: "date", label: "Date" },
    { k: "severity", label: "Severity" }, { k: "status", label: "Status" },
  ];

  if (!rows.length) return <EmptyState title="No exceptions match" hint="Try clearing filters or adjusting your search." />;

  return (
    <div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              {cols.filter((c) => !c.hide).map((c) => (
                <TableHead key={c.k} className="whitespace-nowrap text-xs uppercase tracking-wide">
                  <button className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => setSort((s) => ({ k: c.k, dir: s.k === c.k ? (s.dir === 1 ? -1 : 1) : 1 }))}>
                    {c.label}
                    {sort.k === c.k ? (sort.dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />) : <ArrowUpDown className="size-3 opacity-40" />}
                  </button>
                </TableHead>
              ))}
              <TableHead className="text-right text-xs uppercase tracking-wide">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="font-mono text-xs">{e.id}</TableCell>
                <TableCell className="whitespace-nowrap font-medium">{e.employee.name}</TableCell>
                {!compact && <TableCell className="font-mono text-xs text-muted-foreground">{e.employee.id}</TableCell>}
                {!compact && <TableCell className="text-muted-foreground">{e.employee.department}</TableCell>}
                <TableCell className="whitespace-nowrap">{e.type}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDate(e.date)}</TableCell>
                <TableCell><SeverityBadge severity={e.severity} /></TableCell>
                <TableCell><StatusBadge status={e.status} /></TableCell>
                <TableCell className="text-right">
                  <Button asChild size="sm" variant="outline">
                    <Link to="/exceptions/$id" params={{ id: e.id }}><Eye className="size-3.5" /> View details</Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {pages > 1 && (
        <div className="flex items-center justify-between border-t px-4 py-3 text-sm text-muted-foreground">
          <span>Showing {p * pageSize + 1}–{Math.min(sorted.length, (p + 1) * pageSize)} of {sorted.length}</span>
          <div className="flex items-center gap-2">
            <Button size="icon" variant="outline" className="size-8" disabled={p === 0} onClick={() => setPage(p - 1)} aria-label="Previous page"><ChevronLeft className="size-4" /></Button>
            <span>Page {p + 1} / {pages}</span>
            <Button size="icon" variant="outline" className="size-8" disabled={p >= pages - 1} onClick={() => setPage(p + 1)} aria-label="Next page"><ChevronRight className="size-4" /></Button>
          </div>
        </div>
      )}
    </div>
  );
}
