import { redirect } from "next/navigation";

import { EventManager } from "@/components/events/event-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { EventSummary } from "@/types/api";

export default async function EventsPage() {
  const session = await requireSession();
  const canAdmin = session.user?.is_superadmin || session.current_role === "admin";

  if (!canAdmin) {
    redirect("/");
  }

  const events = await backendFetchWithSession<EventSummary[]>("/api/events");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Datensaetze</div>
        <h1>Termine</h1>
        <p className="muted">
          Pflege hier Termine mit Datum, Titel, Beschreibung und Tag. Darauf koennen wir spaeter gezielt Protokollpunkte aufsetzen.
        </p>
        <EventManager initialEvents={events ?? []} />
      </section>
    </AppShell>
  );
}
