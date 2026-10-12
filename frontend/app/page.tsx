import { getTranslations } from "next-intl/server";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { dashboardTabs } from "@/components/ui/section-tabs";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { MobileDashboard } from "@/components/mobile/mobile-dashboard";
import { dashboardPermissions } from "@/components/dashboard/dashboard-permissions";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, NextSessionInfo, ProtocolSummary, TodoListItem } from "@/types/api";

export default async function HomePage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const access = { role: session.current_role ?? null, features: session.current_tenant?.enabled_features ?? [] };
  const permissions = dashboardPermissions(access);

  // Bussen nur laden, wenn Finanzen gebucht sind (sonst 403). Limit 200 = Backend-Maximum, damit
  // Summe und Personenzahl der offenen Bussen nicht nach 50 Eintraegen abbrechen.
  const [todos, fines, upcomingSessions, protocols] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    permissions.hasFinance ? backendFetchWithSession<AttendanceFineListItem[]>("/api/fines?limit=200") : Promise.resolve([]),
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
            access={access}
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
              access={access}
              hasProtocols={hasProtocols}
              userName={session.user?.first_name || session.user?.display_name || ""}
            />
          </>
        }
      />
    </AppShell>
  );
}
