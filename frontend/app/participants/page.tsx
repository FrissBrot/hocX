import { redirect } from "next/navigation";

import { ParticipantManager } from "@/components/participants/participant-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

export default async function ParticipantsPage() {
  const session = await requireSession();
  const canAdmin = session.user?.is_superadmin || session.current_role === "admin";

  if (!canAdmin) {
    redirect("/");
  }

  const [participants, templates] = await Promise.all([
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Datensaetze</div>
        <h1>Teilnehmer</h1>
        <p className="muted">
          Pflege hier mandantenweite Teilnehmerlisten. Diese Personen koennen Templates zugeordnet und in Todos direkt ausgewaehlt werden.
        </p>
        <ParticipantManager initialParticipants={participants ?? []} templates={templates ?? []} />
      </section>
    </AppShell>
  );
}
