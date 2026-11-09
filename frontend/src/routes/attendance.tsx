import { createFileRoute } from "@tanstack/react-router";
import { employees } from "@/lib/api/mock-data";
import { PageHeader } from "@/components/app/states";
import { Pill } from "@/components/app/badges";
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
      { name: "description", content: "Today's employee attendance and shift records." },
      { property: "og:title", content: "Attendance Records – SmartAttend AI" },
      { property: "og:description", content: "Today's employee attendance and shift records." },
    ],
  }),
  component: Attendance,
});

const states = [
  "Present",
  "Present",
  "Present",
  "Late",
  "Present",
  "On leave",
  "Present",
  "Absent",
] as const;
const tone = { Present: "success", Late: "warning", "On leave": "info", Absent: "danger" } as const;

function Attendance() {
  return (
    <>
      <PageHeader
        title="Attendance Records"
        description="Read-only view of today's attendance (sample data)."
      />
      <div className="card-elevated overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              {["Employee", "ID", "Department", "Shift", "Scheduled", "Status"].map((h) => (
                <TableHead key={h} className="text-xs uppercase tracking-wide">
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {employees.map((e, i) => {
              const s = states[i % states.length]!;
              return (
                <TableRow key={e.id}>
                  <TableCell className="font-medium">{e.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{e.id}</TableCell>
                  <TableCell>{e.department}</TableCell>
                  <TableCell>{e.shift}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {e.shiftStart}–{e.shiftEnd}
                  </TableCell>
                  <TableCell>
                    <Pill t={tone[s]} dot>
                      {s}
                    </Pill>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
