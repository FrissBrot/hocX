import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { HikingTourManager } from "@/components/wanderplaner/hiking-tour-manager";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { HikingTourSummary } from "@/types/api";

export default async function WanderplanerPage() {
  const session = await requireSession();
  const hasFeature = session.current_tenant?.enabled_features?.includes("wanderplaner") ?? false;
  if (!hasFeature) redirect("/");

  const tours = (await backendFetchWithSession<HikingTourSummary[]>("/api/hiking-tours")) ?? [];
  const canWrite = ["admin", "writer"].includes(session.current_role ?? "");

  return (
    <AppShell initialSession={session}>
      <HikingTourManager initialTours={tours} canWrite={canWrite} />
    </AppShell>
  );
}
