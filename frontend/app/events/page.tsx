import { redirect } from "next/navigation";

import { EventManager } from "@/components/events/event-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { EventSummary } from "@/types/api";

export default async function EventsPage() {
  const session = await requireSession();
  const canWrite = session.user?.is_superadmin || session.current_role === "admin" || session.current_role === "writer";

  if (!canWrite) {
    redirect("/");
  }

  const events = await backendFetchWithSession<EventSummary[]>("/api/events");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <EventManager initialEvents={events ?? []} />
      </section>
    </AppShell>
  );
}
