import { AppShell } from "@/components/ui/app-shell";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { MarketingLanding } from "@/components/marketing/marketing-landing";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { getDocsUrl, getMainAppUrl, isMarketingVariant } from "@/lib/site-config";
import { AttendanceFineListItem, NextSessionInfo, TodoListItem } from "@/types/api";

export default async function HomePage() {
  if (isMarketingVariant()) {
    return (
      <MarketingLanding
        appUrl={getMainAppUrl()}
        docsUrl={getDocsUrl()}
        version={process.env.HOCX_VERSION || "live"}
      />
    );
  }

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
