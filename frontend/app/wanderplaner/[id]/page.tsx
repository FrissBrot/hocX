import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { HikingTourDetail } from "@/components/wanderplaner/hiking-tour-detail";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { HikingTour } from "@/types/api";

export default async function WanderplanerTourPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  const hasFeature = session.current_tenant?.enabled_features?.includes("wanderplaner") ?? false;
  if (!hasFeature) redirect("/");

  const tour = await backendFetchWithSession<HikingTour>(`/api/hiking-tours/${id}`);
  if (!tour) {
    redirect("/wanderplaner");
  }
  const canWrite = ["admin", "writer"].includes(session.current_role ?? "");

  return (
    <AppShell initialSession={session}>
      <HikingTourDetail initialTour={tour} canWrite={canWrite} />
    </AppShell>
  );
}
