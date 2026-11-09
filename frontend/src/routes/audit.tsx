import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { allAuditQuery } from "@/lib/api/queries";
import { ErrorState, PageHeader, RowsSkeleton } from "@/components/app/states";
import { AuditTimeline } from "@/components/app/audit-timeline";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";

export const Route = createFileRoute("/audit")({
  head: () => ({
    meta: [
      { title: "Audit Trail – SmartAttend AI" },
      {
        name: "description",
        content: "Every detection, AI, validation and manager action with trace IDs.",
      },
      { property: "og:title", content: "Audit Trail – SmartAttend AI" },
      {
        property: "og:description",
        content: "Every detection, AI, validation and manager action with trace IDs.",
      },
    ],
  }),
  component: Audit,
});

function Audit() {
  const { data, isLoading, error, refetch } = useQuery(allAuditQuery());
  const [q, setQ] = useState("");
  const f = (data ?? []).filter(
    (e) =>
      !q ||
      `${e.exceptionId} ${e.traceId} ${e.user} ${e.action}`.toLowerCase().includes(q.toLowerCase()),
  );
  const body = (rows: typeof f) =>
    error ? (
      <ErrorState error={error} onRetry={refetch} />
    ) : isLoading ? (
      <RowsSkeleton />
    ) : (
      <AuditTimeline events={rows} showException />
    );
  return (
    <>
      <PageHeader
        title="Audit Trail"
        description="Immutable history of every action taken on attendance exceptions."
      />
      <Tabs defaultValue="all">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <TabsList>
            <TabsTrigger value="all">All events</TabsTrigger>
            <TabsTrigger value="flags">Retries & fallbacks</TabsTrigger>
            <TabsTrigger value="escalated">Escalated</TabsTrigger>
          </TabsList>
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter by exception, trace ID, user…"
            className="h-9 max-w-xs"
          />
        </div>
        <TabsContent value="all">{body(f.slice(0, 80))}</TabsContent>
        <TabsContent value="flags">
          {body(f.filter((e) => e.flags.includes("Retried") || e.flags.includes("Fallback")))}
        </TabsContent>
        <TabsContent value="escalated">
          {body(f.filter((e) => e.flags.includes("Escalated")))}
        </TabsContent>
      </Tabs>
    </>
  );
}
