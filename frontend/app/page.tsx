import { getTranslations } from "next-intl/server";
import { AppShell } from "@/components/ui/app-shell";
import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import { RouteTabs } from "@/components/ui/route-tabs";
import { dashboardTabs } from "@/components/ui/section-tabs";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import { MobileDashboard } from "@/components/mobile/mobile-dashboard";
import { dashboardPermissions } from "@/components/dashboard/dashboard-permissions";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { AttendanceFineListItem, NextSessionInfo, OpenFinesSummary, ProtocolSummary, TodoListItem } from "@/types/api";
import "@/app/styles/home.css";

export default async function HomePage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const access = { permissions: session.permissions ?? [], features: session.current_tenant?.enabled_features ?? [] };
  const permissions = dashboardPermissions(access);

  // Bussen nur laden, wenn Finanzen gebucht sind (sonst 403). Die Liste zeigt nur offene Bussen
  // (die neuesten zuerst); Summe je Währung und Personenzahl rechnet der Server über ALLE offenen
  // Bussen (/api/fines/open-summary) - früher: Summe aus den 200 neuesten aller Status, Währungen gemischt.
  const [todos, fines, fineSummary, upcomingSessions, protocols] = await Promise.all([
    backendFetchWithSession<TodoListItem[]>("/api/todos"),
    permissions.hasFinance ? backendFetchWithSession<AttendanceFineListItem[]>("/api/fines?status=pending&limit=50") : Promise.resolve([]),
    permissions.hasFinance ? backendFetchWithSession<OpenFinesSummary>("/api/fines/open-summary") : Promise.resolve(null),
    backendFetchWithSession<NextSessionInfo[]>("/api/protocols/upcoming-sessions"),
    backendFetchWithSession<ProtocolSummary[]>("/api/protocols?limit=1"),
  ]);

  const hasProtocols = (protocols ?? []).length > 0;

  // Die Startseite liegt direkt unter dem Root-Layout (kein eigenes layout.tsx moeglich), daher
  // liefert sie ihre Uebersetzungs-Namespaces hier selbst nach (lib/i18n/message-scopes.ts).
  return (
    <AreaIntlProvider area="dashboard">
      <AppShell initialSession={session}>
        <ResponsiveView
          mobile={
            <MobileDashboard
              todos={todos ?? []}
              fines={fines ?? []}
              fineSummary={fineSummary ?? null}
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
                fineSummary={fineSummary ?? null}
                upcomingSessions={upcomingSessions ?? []}
                access={access}
                hasProtocols={hasProtocols}
                userName={session.user?.first_name || session.user?.display_name || ""}
              />
            </>
          }
        />
      </AppShell>
    </AreaIntlProvider>
  );
}
