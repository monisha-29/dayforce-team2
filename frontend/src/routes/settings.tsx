import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";
import { API_BASE_URL, USE_MOCK } from "@/lib/api/client";
import { PageHeader } from "@/components/app/states";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings – SmartAttend AI" },
      { name: "description", content: "API connection and notification preferences." },
      { property: "og:title", content: "Settings – SmartAttend AI" },
      { property: "og:description", content: "API connection and notification preferences." },
    ],
  }),
  component: Settings,
});

function Settings() {
  return (
    <>
      <PageHeader title="Settings" description="Workspace preferences for SmartAttend AI." />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card-elevated space-y-4 p-6">
          <h2 className="font-semibold">Backend connection</h2>
          <div className="space-y-1.5"><Label>API base URL</Label><Input readOnly value={API_BASE_URL} className="font-mono" /></div>
          <p className="text-sm text-muted-foreground">Mode: <span className="font-medium text-foreground">{USE_MOCK ? "Mock API (in-browser)" : "Live FastAPI"}</span>. Set <code className="font-mono">VITE_API_BASE_URL</code> and <code className="font-mono">VITE_USE_MOCK_API=false</code> to connect the real backend.</p>
        </section>
        <section className="card-elevated space-y-4 p-6">
          <h2 className="font-semibold">Notifications</h2>
          {["Critical exceptions", "New proposals awaiting approval", "Escalations", "Daily summary email"].map((n, i) => (
            <div key={n} className="flex items-center justify-between"><Label htmlFor={`n${i}`}>{n}</Label><Switch id={`n${i}`} defaultChecked={i < 3} /></div>
          ))}
          <Button onClick={() => toast.success("Preferences saved locally")}>Save preferences</Button>
        </section>
      </div>
    </>
  );
}
