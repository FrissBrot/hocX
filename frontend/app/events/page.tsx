import { redirect } from "next/navigation";

import { EventManager } from "@/components/events/event-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { DocumentTemplate, EventSummary, ParticipantSummary } from "@/types/api";

export default async function EventsPage() {
  const session = await requireSession();
  const canWrite = session.current_role === "admin" || session.current_role === "writer";

  if (!canWrite) {
    redirect("/");
  }

  const [events, documentTemplates, participants] = await Promise.all([
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <EventManager initialEvents={events ?? []} documentTemplates={documentTemplates ?? []} availableParticipants={participants ?? []} />
      </section>
    </AppShell>
  );
}
