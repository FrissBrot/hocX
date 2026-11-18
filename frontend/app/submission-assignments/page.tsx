import { MobileSubmissions } from "@/components/mobile/areas/mobile-submissions";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { SubmissionAssignmentManager } from "@/components/submission-assignments/submission-assignment-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import {
  CycleConfigSummary,
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  SubmissionAssignment,
  SubmissionLink,
  SubmissionReviewerCandidate,
} from "@/types/api";
import { can, featureAccess } from "@/lib/permissions";

export default async function SubmissionAssignmentsPage({ searchParams }: { searchParams: Promise<{ assignment?: string }> }) {
  const session = await requireSession();
  // ?assignment=<public_id> öffnet die Abgabe direkt (Link aus der Dateiübersicht)
  const { assignment: initialAssignmentId } = await searchParams;
  // Lesen genügt (Prüfer, Plan «Berechtigungen» Phase 4); Verwalten und Prüfen schalten die Aktionen frei.
  const canRead = can(session, "submissions.read");
  const canManage = can(session, "submissions.manage");
  const canReview = can(session, "submissions.review");
  const hasAbgabeboxFeature = featureAccess(session, "abgabebox") !== "none";

  if (!canRead || !hasAbgabeboxFeature) {
    redirect("/");
  }

  // Links (mit Token) und Prüfer-Kandidaten nur für die Verwaltung; die übrigen Listen dienen der
  // Anzeige (Quelle, Verantwortliche) und werden nur mit dem jeweiligen Leserecht geladen.
  const [assignments, links, lists, events, participants, cycleConfigs, reviewerCandidates] = await Promise.all([
    backendFetchWithSession<SubmissionAssignment[]>("/api/submission-assignments"),
    canManage ? backendFetchWithSession<SubmissionLink[]>("/api/submission-links") : Promise.resolve(null),
    can(session, "meetings.edit") ? backendFetchWithSession<StructuredListDefinition[]>("/api/lists") : Promise.resolve(null),
    can(session, "meetings.read") ? backendFetchWithSession<EventSummary[]>("/api/events") : Promise.resolve(null),
    can(session, "participants.read") ? backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=500") : Promise.resolve(null),
    can(session, "meetings.read") ? backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs") : Promise.resolve(null),
    canManage ? backendFetchWithSession<SubmissionReviewerCandidate[]>("/api/submission-assignments/reviewer-candidates") : Promise.resolve(null),
  ]);

  const shared = {
    initialAssignments: assignments ?? [],
    initialLinks: links ?? [],
    availableLists: lists ?? [],
    availableEvents: events ?? [],
    availableParticipants: participants ?? [],
    availableCycleConfigs: cycleConfigs ?? [],
    availableReviewers: reviewerCandidates ?? [],
    tenantName: session.current_tenant?.name ?? null,
    canManage,
    canReview,
  };

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileSubmissions {...shared} />}
        desktop={
          <>
          <section className="panel">
            <SubmissionAssignmentManager {...shared} initialSelectedId={initialAssignmentId ?? null} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
