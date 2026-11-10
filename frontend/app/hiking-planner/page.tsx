import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { HikingTourManager } from "@/components/wanderplaner/hiking-tour-manager";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";
import { HikingTourSummary } from "@/types/api";

export default async function WanderplanerPage() {
  const session = await requireSession();
  // can() prüft Berechtigung und Buchung (hiking.* ist an das Feature wanderplaner gebunden)
  if (!can(session, "hiking.read")) redirect("/");

  const tours = (await backendFetchWithSession<HikingTourSummary[]>("/api/hiking-tours")) ?? [];
  const canWrite = can(session, "hiking.manage");

  return (
    <AppShell initialSession={session}>
      <HikingTourManager initialTours={tours} canWrite={canWrite} />
    </AppShell>
  );
}
