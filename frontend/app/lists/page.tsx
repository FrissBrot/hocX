import { redirect } from "next/navigation";

import { ListManager } from "@/components/lists/list-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import {
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
} from "@/types/api";

export default async function ListsPage() {
  const session = await requireSession();
  const canAdmin = session.user?.is_superadmin || session.current_role === "admin";

  if (!canAdmin) {
    redirect("/");
  }

  const [lists, participants, events] = await Promise.all([
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
  ]);

  const listEntryPairs = await Promise.all(
    (lists ?? []).map(async (definition) => ({
      listId: definition.id,
      entries: (await backendFetchWithSession<StructuredListEntry[]>(`/api/lists/${definition.id}/entries`)) ?? [],
    }))
  );
  const initialEntriesByList = Object.fromEntries(listEntryPairs.map((pair) => [pair.listId, pair.entries]));

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Datensaetze</div>
        <h1>Listen</h1>
        <p className="muted">
          Pflege hier globale Zweispalten-Listen. Tabellenbloecke in Elementen koennen direkt an diese Listen gekoppelt werden.
        </p>
        <ListManager
          initialLists={lists ?? []}
          initialEntriesByList={initialEntriesByList}
          availableParticipants={participants ?? []}
          availableEvents={events ?? []}
        />
      </section>
    </AppShell>
  );
}
