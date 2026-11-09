import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ClipboardCheck, UserCheck, Users } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { attendanceSummaryQuery, exceptionsQuery } from "@/lib/api/queries";
import { ErrorState, PageHeader, RowsSkeleton } from "@/components/app/states";
import { ExceptionsTable } from "@/components/app/exceptions-table";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard – SmartAttend AI" },
      {
        name: "description",
        content: "Attendance KPIs, exception distribution and pending manager approvals.",
      },
      { property: "og:title", content: "Dashboard – SmartAttend AI" },
      {
        property: "og:description",
        content: "Attendance KPIs, exception distribution and pending manager approvals.",
      },
    ],
  }),
  component: Dashboard,
});

const tip = { contentStyle: { borderRadius: 8, border: "1px solid var(--border)", fontSize: 12 } };
const pieColors = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];

function Kpi({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  icon: typeof Users;
  hint: string;
}) {
  return (
    <div className="card-elevated p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{label}</p>
        <div className="rounded-lg bg-accent p-2 text-accent-foreground">
          <Icon className="size-4" />
        </div>
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight">{value}</div>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

function Panel({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="card-elevated overflow-hidden">
      <div className="flex items-center justify-between border-b px-5 py-3.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Dashboard() {
  const { data, isLoading, error, refetch } = useQuery(exceptionsQuery());
  const { data: att, isLoading: attLoading } = useQuery(attendanceSummaryQuery());
  const n = (f: (s: string) => boolean) => data?.filter((e) => f(e.status)).length;
  const v = (x: number | undefined, loading = isLoading) =>
    loading ? <Skeleton className="h-9 w-16" /> : (x ?? "—");
  const dist = [
    "Missing Punch",
    "Overtime Risk",
    "Schedule Conflict",
    "Meal Break Violation",
    "Duplicate Punch",
    "Rest Period Violation",
    "Consecutive Days",
  ].map((t) => ({ name: t, value: data?.filter((e) => e.type === t).length ?? 0 }));

  return (
    <>
      <PageHeader
        title="Good morning, Rebecca"
        description="Attendance and exception overview, from the recorded punches."
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Kpi
          label="Total Employees"
          value={v(att?.totalEmployees, attLoading)}
          icon={Users}
          hint={att ? `Across ${att.departments} departments` : "—"}
        />
        <Kpi
          label="Present"
          value={v(att ? att.present + att.late : undefined, attLoading)}
          icon={UserCheck}
          hint={
            att
              ? `${att.date} · ${att.scheduled ? Math.round((100 * (att.present + att.late)) / att.scheduled) : 0}% of ${att.scheduled} scheduled`
              : "—"
          }
        />
        <Kpi
          label="Total Exceptions"
          value={v(data?.length)}
          icon={AlertTriangle}
          hint="All detected"
        />
        <Kpi
          label="Pending Approvals"
          value={v(n((s) => s === "Awaiting Approval"))}
          icon={ClipboardCheck}
          hint="Awaiting your decision"
        />
        <Kpi
          label="Resolved"
          value={v(n((s) => s === "Approved" || s === "Rejected"))}
          icon={CheckCircle2}
          hint="Approved or rejected"
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title={`Attendance overview · week of ${att?.days[0]?.date ?? "—"}`}>
            <div className="h-72 p-4">
              <ResponsiveContainer>
                <BarChart data={att?.days ?? []}>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis tickLine={false} axisLine={false} fontSize={12} />
                  <Tooltip {...tip} cursor={{ fill: "var(--muted)" }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="present" name="Present" stackId="a" fill="var(--chart-1)" />
                  <Bar dataKey="late" name="Late" stackId="a" fill="var(--chart-3)" />
                  <Bar
                    dataKey="absent"
                    name="Absent"
                    stackId="a"
                    fill="var(--chart-4)"
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>
        <Panel title="Exception distribution">
          <div className="h-72 p-4">
            {isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : (
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={dist}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={55}
                    outerRadius={85}
                    paddingAngle={2}
                  >
                    {dist.map((_, i) => (
                      <Cell key={i} fill={pieColors[i]} />
                    ))}
                  </Pie>
                  <Tooltip {...tip} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel
            title="Recent attendance exceptions"
            action={
              <Button asChild variant="link" size="sm">
                <Link to="/exceptions">View queue</Link>
              </Button>
            }
          >
            {error ? (
              <div className="p-4">
                <ErrorState error={error} onRetry={refetch} />
              </div>
            ) : isLoading ? (
              <RowsSkeleton rows={5} />
            ) : (
              <ExceptionsTable rows={data!.slice(0, 6)} pageSize={6} compact />
            )}
          </Panel>
        </div>
        <div className="space-y-6">
          <Panel
            title="Pending manager approvals"
            action={
              <Button asChild variant="link" size="sm">
                <Link to="/approvals">All</Link>
              </Button>
            }
          >
            <ul className="divide-y">
              {isLoading && <RowsSkeleton rows={4} />}
              {data
                ?.filter((e) => e.status === "Awaiting Approval")
                .slice(0, 5)
                .map((e) => (
                  <li key={e.id}>
                    <Link
                      to="/exceptions/$id"
                      params={{ id: e.id }}
                      className="flex items-center justify-between px-5 py-3 text-sm hover:bg-muted/50"
                    >
                      <div>
                        <p className="font-medium">{e.employee.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {e.type} · {e.id}
                        </p>
                      </div>
                      <span className="text-xs font-medium text-primary">Review →</span>
                    </Link>
                  </li>
                ))}
            </ul>
          </Panel>
          <Panel title="Weekly attendance trend">
            <div className="h-48 p-4">
              <ResponsiveContainer>
                <AreaChart data={att?.weeks ?? []}>
                  <defs>
                    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--chart-2)" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="var(--chart-2)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="week" tickLine={false} axisLine={false} fontSize={11} />
                  <YAxis
                    domain={[0, 100]}
                    tickLine={false}
                    axisLine={false}
                    fontSize={11}
                    unit="%"
                    width={40}
                  />
                  <Tooltip {...tip} />
                  <Area
                    dataKey="rate"
                    name="Attendance rate"
                    stroke="var(--chart-1)"
                    strokeWidth={2}
                    fill="url(#g)"
                    unit="%"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
