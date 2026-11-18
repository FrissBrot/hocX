import { MobileStatistics } from "@/components/mobile/areas/mobile-statistics";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { dashboardTabs } from "@/components/ui/section-tabs";
import { StatisticsView } from "@/components/statistics/statistics-view";
import { statisticsPath } from "@/components/statistics/statistics-model";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { StatisticsOverview } from "@/types/api";

// Schweizer «heute» (wie das Backend), damit das laufende Jahr am Jahreswechsel stimmt.
function zurichToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Zurich", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export default async function StatisticsPage() {
  const session = await requireSession();
  const t = await getTranslations("nav");
  const today = zurichToday();
  const year = Number(today.slice(0, 4));
  // Dashboard v2: laufendes Kalenderjahr, mit Vorjahresvergleich.
  const data = (await backendFetchWithSession<StatisticsOverview>(statisticsPath(year, true))) ?? null;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileStatistics data={data} year={year} today={today} />}
        desktop={
          <>
            <RouteTabs tabs={dashboardTabs(t)} activeHref="/statistics" />
            <StatisticsView data={data} year={year} today={today} />
          </>
        }
      />
    </AppShell>
  );
}
