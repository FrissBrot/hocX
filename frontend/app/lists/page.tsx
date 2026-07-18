import { redirect } from "next/navigation";

import { ListManager } from "@/components/lists/list-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import {
  DocumentTemplate,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
} from "@/types/api";

export default async function ListsPage() {
  const session = await requireSession();
  const canWrite = session.current_role === "admin" || session.current_role === "writer";

  if (!canWrite) {
    redirect("/");
  }

  const [lists, participants, events, documentTemplates] = await Promise.all([
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
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
        <ListManager
          initialLists={lists ?? []}
          initialEntriesByList={initialEntriesByList}
          availableParticipants={participants ?? []}
          availableEvents={events ?? []}
          documentTemplates={documentTemplates ?? []}
        />
      </section>
    </AppShell>
  );
}
