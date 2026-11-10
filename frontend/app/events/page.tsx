import { redirect } from "next/navigation";

import { EventManager } from "@/components/events/event-manager";
import { MobileEvents } from "@/components/mobile/mobile-events";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { EventSummary, ParticipantSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function EventsPage() {
  const session = await requireSession();
  const canWrite = can(session, "meetings.edit");

  if (!canWrite) {
    redirect("/");
  }

  const [events, participants] = await Promise.all([
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500"),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileEvents initialEvents={events ?? []} participants={participants ?? []} />}
        desktop={
          <section className="panel">
            <EventManager
              initialEvents={events ?? []}
              availableParticipants={participants ?? []}
              tenantName={session.current_tenant?.name ?? null}
            />
          </section>
        }
      />
    </AppShell>
  );
}
