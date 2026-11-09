import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RotateCw } from "lucide-react";
import { attendanceQuery } from "@/lib/api/queries";
import type { AttendanceStatus } from "@/lib/api/types";
import { ErrorState, PageHeader, RowsSkeleton } from "@/components/app/states";
import { Pill } from "@/components/app/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/attendance")({
  head: () => ({
    meta: [
      { title: "Attendance Records – SmartAttend AI" },
      { name: "description", content: "Employee attendance and shift records for a day." },
      { property: "og:title", content: "Attendance Records – SmartAttend AI" },
      {
        property: "og:description",
        content: "Employee attendance and shift records for a day.",
      },
    ],
  }),
  component: Attendance,
});

const tone = { Present: "success", Late: "warning", Absent: "danger" } as const;

function Attendance() {
  const [date, setDate] = useState<string | undefined>(undefined);
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    ...attendanceQuery(date),
    placeholderData: (p) => p,
  });

  const count = (s: AttendanceStatus) => data?.records.filter((r) => r.status === s).length ?? 0;

  return (
    <>
      <PageHeader
        title="Attendance Records"
        description="Read-only. Who was scheduled and who actually clocked in, from the recorded punches."
        actions={
          <div className="flex items-center gap-2">
            <Input
              type="date"
              aria-label="Attendance date"
              className="h-9 w-40"
              value={date ?? data?.date ?? ""}
              min={data?.minDate ?? undefined}
              max={data?.maxDate ?? undefined}
              onChange={(e) => setDate(e.target.value || undefined)}
            />
            <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
              <RotateCw className={isFetching ? "size-4 animate-spin" : "size-4"} /> Refresh
            </Button>
          </div>
        }
      />
      {error ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : isLoading || !data ? (
        <RowsSkeleton />
      ) : (
        <>
          <p className="mb-3 text-sm text-muted-foreground" data-testid="attendance-summary">
            {data.records.length} scheduled or working on {data.date}: {count("Present")} present,{" "}
            {count("Late")} late, {count("Absent")} absent.
          </p>
          <div className="card-elevated overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  {[
                    "Employee",
                    "ID",
                    "Department",
                    "Scheduled",
                    "Clock-in",
                    "Clock-out",
                    "Status",
                    "Exceptions",
                  ].map((h) => (
                    <TableHead key={h} className="text-xs uppercase tracking-wide">
                      {h}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.records.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                      No attendance data for this day.
                    </TableCell>
                  </TableRow>
                )}
                {data.records.map((r) => (
                  <TableRow key={r.employeeId}>
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {r.employeeId}
                    </TableCell>
                    <TableCell>{r.department}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {r.scheduledStart ? `${r.scheduledStart}–${r.scheduledEnd}` : "Unscheduled"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{r.checkIn ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{r.checkOut ?? "—"}</TableCell>
                    <TableCell>
                      <Pill t={tone[r.status]} dot>
                        {r.status}
                      </Pill>
                    </TableCell>
                    <TableCell className="text-xs">
                      {r.exceptionIds.length === 0
                        ? "—"
                        : r.exceptionIds.map((id) => (
                            <Link
                              key={id}
                              to="/exceptions/$id"
                              params={{ id }}
                              className="mr-2 font-mono text-primary underline-offset-2 hover:underline"
                            >
                              {id}
                            </Link>
                          ))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </>
  );
}
