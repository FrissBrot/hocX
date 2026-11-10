import { MobileParticipants } from "@/components/mobile/areas/mobile-participants";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { ParticipantManager } from "@/components/participants/participant-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ParticipantSummary, TemplateSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function ParticipantsPage() {
  const session = await requireSession();
  const canWrite = can(session, "participants.manage");

  if (!canWrite) {
    redirect("/");
  }

  const [participants, templates] = await Promise.all([
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=50"),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileParticipants initialParticipants={participants ?? []} templates={templates ?? []} tenantId={session.current_tenant?.id ?? null} />}
        desktop={
          <>
          <section className="panel">
            <ParticipantManager
              initialParticipants={participants ?? []}
              templates={templates ?? []}
              canAdmin={can(session, "access.manage")}
              tenantId={session.current_tenant?.id ?? null}
            />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
