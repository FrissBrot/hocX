import { redirect } from "next/navigation";

import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { HikingTourDetail } from "@/components/wanderplaner/hiking-tour-detail";
import { HikingTourMobile } from "@/components/wanderplaner/hiking-tour-mobile";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";
import { HikingTour } from "@/types/api";

export default async function WanderplanerTourPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  // can() prüft Berechtigung und Buchung (hiking.* ist an das Feature wanderplaner gebunden)
  if (!can(session, "hiking.read")) redirect("/");

  const tour = await backendFetchWithSession<HikingTour>(`/api/hiking-tours/${id}`);
  if (!tour) {
    redirect("/hiking-planner");
  }
  const canWrite = can(session, "hiking.manage");

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<HikingTourMobile initialTour={tour} canWrite={canWrite} />}
        desktop={<HikingTourDetail initialTour={tour} canWrite={canWrite} />}
      />
    </AppShell>
  );
}
