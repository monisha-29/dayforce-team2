import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  AlertOctagon,
  Bell,
  CalendarDays,
  ClipboardCheck,
  History,
  LayoutDashboard,
  ListChecks,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { USE_MOCK } from "@/lib/api/client";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/exceptions", label: "Exception Queue", icon: ListChecks },
  { to: "/attendance", label: "Attendance Records", icon: Users },
  { to: "/approvals", label: "Manager Approvals", icon: ClipboardCheck },
  { to: "/audit", label: "Audit Trail", icon: History },
  { to: "/escalated", label: "Escalated Cases", icon: AlertOctagon },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid size-8 place-items-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
        <ShieldCheck className="size-4.5" />
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-sidebar-primary">SmartAttend AI</p>
        <p className="text-[11px] text-sidebar-foreground/70">Exception Resolution</p>
      </div>
    </div>
  );
}

function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav className="flex flex-col gap-0.5 px-3">
      {nav.map((n) => {
        const active = n.to === "/" ? path === "/" : path.startsWith(n.to);
        return (
          <Link
            key={n.to}
            to={n.to}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              active
                ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                : "text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
            )}
          >
            <n.icon className="size-4" />
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const [today, setToday] = useState("");
  useEffect(
    () =>
      setToday(
        new Date().toLocaleDateString("en-US", {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        }),
      ),
    [],
  );

  const sidebar = (
    <div className="flex h-full flex-col bg-sidebar py-5">
      <div className="mb-6 px-6">
        <Logo />
      </div>
      <SideNav onNavigate={() => setOpen(false)} />
      <div className="mt-auto mx-3 rounded-lg border border-sidebar-border p-3 text-xs text-sidebar-foreground/80">
        <p className="font-medium text-sidebar-primary">
          {USE_MOCK ? "Mock API mode" : "Live API"}
        </p>
        <p className="mt-1">Demo data is fictional. No real timecards are modified.</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-foreground/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 animate-in slide-in-from-left">
            {sidebar}
          </aside>
        </div>
      )}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-card/90 px-4 backdrop-blur md:px-8">
          <button
            className="rounded-md p-2 hover:bg-muted lg:hidden"
            onClick={() => setOpen(!open)}
            aria-label="Toggle navigation"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
          <form
            className="relative w-full max-w-md"
            onSubmit={(e) => {
              e.preventDefault();
              navigate({ to: "/exceptions", search: { q } });
            }}
          >
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search employee name, ID or exception…"
              className="h-9 bg-muted/60 pl-9"
            />
          </form>
          <div className="ml-auto flex items-center gap-2 md:gap-4">
            <span className="hidden items-center gap-1.5 text-sm text-muted-foreground md:flex">
              <CalendarDays className="size-4" />
              {today}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger
                className="relative rounded-md p-2 hover:bg-muted"
                aria-label="Notifications"
              >
                <Bell className="size-5" />
                <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-destructive" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuLabel>Notifications</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link to="/exceptions/$id" params={{ id: "EXC-2402" }}>
                    Critical overtime risk — Lena Fischer
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to="/escalated">3 cases escalated to HR Operations</Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to="/approvals">8 proposals awaiting your approval</Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <div className="flex items-center gap-2.5">
              <div className="grid size-8 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                RT
              </div>
              <div className="hidden leading-tight sm:block">
                <p className="text-sm font-medium">Rebecca Thorne</p>
                <p className="text-xs text-muted-foreground">Operations Manager</p>
              </div>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] p-4 md:p-8 animate-in fade-in duration-300">
          {children}
        </main>
      </div>
    </div>
  );
}
