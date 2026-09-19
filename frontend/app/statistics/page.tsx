import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { DASHBOARD_TABS } from "@/components/ui/section-tabs";
import { StatisticsView } from "@/components/statistics/statistics-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { StatisticsOverview } from "@/types/api";

export default async function StatisticsPage() {
  const session = await requireSession();
  const data = await backendFetchWithSession<StatisticsOverview>("/api/statistics/overview") ?? null;

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={DASHBOARD_TABS} activeHref="/statistics" />
      <StatisticsView data={data} />
    </AppShell>
  );
}
