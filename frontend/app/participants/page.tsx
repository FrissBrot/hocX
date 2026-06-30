import { redirect } from "next/navigation";

import { ParticipantManager } from "@/components/participants/participant-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

export default async function ParticipantsPage() {
  const session = await requireSession();
  const canWrite = session.user?.is_superadmin || session.current_role === "admin" || session.current_role === "writer";

  if (!canWrite) {
    redirect("/");
  }

  const [participants, templates] = await Promise.all([
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <ParticipantManager initialParticipants={participants ?? []} templates={templates ?? []} />
      </section>
    </AppShell>
  );
}
