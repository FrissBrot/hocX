import { redirect } from "next/navigation";

import { SubmissionAssignmentManager } from "@/components/submission-assignments/submission-assignment-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { EventSummary, ParticipantSummary, StructuredListDefinition, SubmissionAssignment, SubmissionLink } from "@/types/api";

export default async function SubmissionAssignmentsPage() {
  const session = await requireSession();
  const canWrite = session.current_role === "admin" || session.current_role === "writer";

  if (!canWrite) {
    redirect("/");
  }

  const [assignments, links, lists, events, participants] = await Promise.all([
    backendFetchWithSession<SubmissionAssignment[]>("/api/submission-assignments"),
    backendFetchWithSession<SubmissionLink[]>("/api/submission-links"),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500"),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <SubmissionAssignmentManager initialAssignments={assignments ?? []} initialLinks={links ?? []} availableLists={lists ?? []} availableEvents={events ?? []} availableParticipants={participants ?? []} />
      </section>
    </AppShell>
  );
}
