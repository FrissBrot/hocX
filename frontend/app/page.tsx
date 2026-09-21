import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { DASHBOARD_TABS } from "@/components/ui/section-tabs";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, NextSessionInfo, ProtocolSummary, TodoListItem } from "@/types/api";

export default async function HomePage() {
  const session = await requireSession();
  const canExcuse = ["admin", "writer"].includes(session.current_role ?? "");

  const [todos, fines, nextSession, protocols] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    backendFetchWithSession<AttendanceFineListItem[]>("/api/fines"),
    backendFetchWithSession<NextSessionInfo>("/api/protocols/next-session"),
    backendFetchWithSession<ProtocolSummary[]>("/api/protocols?limit=1"),
  ]);

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={DASHBOARD_TABS} activeHref="/" />
      <DashboardView
        todos={todos ?? []}
        fines={fines ?? []}
        nextSession={nextSession ?? { protocol: null, attendance_block_id: null, entries: [] }}
        canExcuse={canExcuse}
        canWrite={canExcuse}
        canConfigure={session.current_role === "admin"}
        hasProtocols={(protocols ?? []).length > 0}
      />
    </AppShell>
  );
}
