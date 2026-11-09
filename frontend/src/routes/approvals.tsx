import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { exceptionsQuery } from "@/lib/api/queries";
import { ErrorState, PageHeader, RowsSkeleton } from "@/components/app/states";
import { ExceptionsTable } from "@/components/app/exceptions-table";

export const Route = createFileRoute("/approvals")({
  head: () => ({
    meta: [
      { title: "Manager Approvals – SmartAttend AI" },
      {
        name: "description",
        content: "AI-proposed timecard corrections awaiting manager decision.",
      },
      { property: "og:title", content: "Manager Approvals – SmartAttend AI" },
      {
        property: "og:description",
        content: "AI-proposed timecard corrections awaiting manager decision.",
      },
    ],
  }),
  component: function ApprovalsPage() {
    const { data, isLoading, error, refetch } = useQuery(
      exceptionsQuery({ status: "Awaiting Approval" }),
    );
    return (
      <>
        <PageHeader
          title="Manager Approvals"
          description="Validated AI proposals waiting for your approve, edit or reject decision."
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
  },
});
