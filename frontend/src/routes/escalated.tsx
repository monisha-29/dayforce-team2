import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { exceptionsQuery } from "@/lib/api/queries";
import { ErrorState, PageHeader, RowsSkeleton } from "@/components/app/states";
import { ExceptionsTable } from "@/components/app/exceptions-table";

export const Route = createFileRoute("/escalated")({
  head: () => ({
    meta: [
      { title: "Escalated Cases – SmartAttend AI" },
      {
        name: "description",
        content: "Exceptions escalated to HR Operations for manual handling.",
      },
      { property: "og:title", content: "Escalated Cases – SmartAttend AI" },
      {
        property: "og:description",
        content: "Exceptions escalated to HR Operations for manual handling.",
      },
    ],
  }),
  component: EscalatedPage,
});

function EscalatedPage() {
  const { data, isLoading, error, refetch } = useQuery(exceptionsQuery({ status: "Escalated" }));
  return (
    <>
      <PageHeader
        title="Escalated Cases"
        description="AI fallback, blocked proposals and manager escalations requiring manual review."
      />
      <div className="card-elevated overflow-hidden">
        {error ? (
          <div className="p-4">
            <ErrorState error={error} onRetry={refetch} />
          </div>
        ) : isLoading ? (
          <RowsSkeleton />
        ) : (
          <ExceptionsTable rows={data!} />
        )}
      </div>
    </>
  );
}
