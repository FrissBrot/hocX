import { MobileLists } from "@/components/mobile/areas/mobile-lists";
import { ResponsiveView } from "@/components/mobile/responsive-view";
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
import { can } from "@/lib/permissions";

export default async function ListsPage() {
  const session = await requireSession();
  const canWrite = can(session, "meetings.edit");

  if (!canWrite) {
    redirect("/");
  }

  // Einträge aller Listen in einem Aufruf (Audit 07, C6: vorher ein Request je Liste).
  const [lists, entriesByList, participants, events] = await Promise.all([
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<Record<string, StructuredListEntry[]>>("/api/list-entries"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=2000"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
  ]);

  const initialEntriesByList = Object.fromEntries((lists ?? []).map((definition) => [definition.id, entriesByList?.[definition.id] ?? []]));

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileLists initialLists={lists ?? []} initialEntriesByList={initialEntriesByList} participants={participants ?? []} events={events ?? []} />}
        desktop={
          <>
          <section className="panel lists-page">
            <ListManager
              initialLists={lists ?? []}
              initialEntriesByList={initialEntriesByList}
              availableParticipants={participants ?? []}
              availableEvents={events ?? []}
            />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
