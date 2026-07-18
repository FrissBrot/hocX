import { AppShell } from "@/components/ui/app-shell";
import { StatisticsView } from "@/components/statistics/statistics-view";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { StatisticsOverview } from "@/types/api";

export default async function StatisticsPage() {
  const session = await requireSession();
  const data = await backendFetchWithSession<StatisticsOverview>("/api/statistics/overview") ?? null;

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <StatisticsView data={data} />
      </section>
    </AppShell>
  );
}
