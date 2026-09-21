import { redirect } from "next/navigation";

import { SubmissionAssignmentManager } from "@/components/submission-assignments/submission-assignment-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, EventSummary, ParticipantSummary, StructuredListDefinition, SubmissionAssignment, SubmissionLink } from "@/types/api";

export default async function SubmissionAssignmentsPage() {
  const session = await requireSession();
  const canWrite = session.current_role === "admin" || session.current_role === "writer";

  if (!canWrite) {
    redirect("/");
  }

  const [assignments, links, lists, events, participants, cycleConfigs] = await Promise.all([
    backendFetchWithSession<SubmissionAssignment[]>("/api/submission-assignments"),
    backendFetchWithSession<SubmissionLink[]>("/api/submission-links"),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <SubmissionAssignmentManager initialAssignments={assignments ?? []} initialLinks={links ?? []} availableLists={lists ?? []} availableEvents={events ?? []} availableParticipants={participants ?? []} availableCycleConfigs={cycleConfigs ?? []} tenantName={session.current_tenant?.name ?? null} />
      </section>
    </AppShell>
  );
}
