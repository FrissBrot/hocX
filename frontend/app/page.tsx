import { getTranslations } from "next-intl/server";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { dashboardTabs } from "@/components/ui/section-tabs";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { MobileDashboard } from "@/components/mobile/mobile-dashboard";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, NextSessionInfo, ProtocolSummary, TodoListItem } from "@/types/api";

export default async function HomePage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const canExcuse = ["admin", "writer"].includes(session.current_role ?? "");

  const [todos, fines, upcomingSessions, protocols] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    backendFetchWithSession<AttendanceFineListItem[]>("/api/fines"),
    backendFetchWithSession<NextSessionInfo[]>("/api/protocols/upcoming-sessions"),
    backendFetchWithSession<ProtocolSummary[]>("/api/protocols?limit=1"),
  ]);

  const hasProtocols = (protocols ?? []).length > 0;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={
          <MobileDashboard
            todos={todos ?? []}
            fines={fines ?? []}
            upcomingSessions={upcomingSessions ?? []}
            canExcuse={canExcuse}
            canWrite={canExcuse}
            hasProtocols={hasProtocols}
          />
        }
        desktop={
          <>
            <RouteTabs tabs={dashboardTabs(t)} activeHref="/" />
            <DashboardView
              todos={todos ?? []}
              fines={fines ?? []}
              upcomingSessions={upcomingSessions ?? []}
              canExcuse={canExcuse}
              canWrite={canExcuse}
              canConfigure={session.current_role === "admin"}
              hasProtocols={hasProtocols}
            />
          </>
        }
      />
    </AppShell>
  );
}
