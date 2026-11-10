import { MobileStatistics } from "@/components/mobile/areas/mobile-statistics";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { dashboardTabs } from "@/components/ui/section-tabs";
import { StatisticsView } from "@/components/statistics/statistics-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { StatisticsOverview } from "@/types/api";

export default async function StatisticsPage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const data = await backendFetchWithSession<StatisticsOverview>("/api/statistics/overview") ?? null;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileStatistics data={data} />}
        desktop={
          <>
          <RouteTabs tabs={dashboardTabs(t)} activeHref="/statistics" />
          <StatisticsView data={data} />
          </>
        }
      />
    </AppShell>
  );
}
