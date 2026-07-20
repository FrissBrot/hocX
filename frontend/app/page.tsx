import { AppShell } from "@/components/ui/app-shell";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, NextSessionInfo, TodoListItem } from "@/types/api";

export default async function HomePage() {
  const session = await requireSession();
  const canExcuse = ["admin", "writer"].includes(session.current_role ?? "");

  const [todos, fines, nextSession] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    backendFetchWithSession<AttendanceFineListItem[]>("/api/fines"),
    backendFetchWithSession<NextSessionInfo>("/api/protocols/next-session"),
  ]);

  return (
    <AppShell initialSession={session}>
      <DashboardView
        todos={todos ?? []}
        fines={fines ?? []}
        nextSession={nextSession ?? { protocol: null, attendance_block_id: null, entries: [] }}
        canExcuse={canExcuse}
      />
    </AppShell>
  );
}
