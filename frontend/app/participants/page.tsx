import { MobileParticipants } from "@/components/mobile/areas/mobile-participants";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { ParticipantManager } from "@/components/participants/participant-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { FineTariffGroup, ParticipantSummary, RoleRead, TemplateSummary } from "@/types/api";
import { can, featureAccess } from "@/lib/permissions";

export default async function ParticipantsPage({ searchParams }: { searchParams: Promise<{ tariff?: string }> }) {
  const session = await requireSession();
  const canWrite = can(session, "participants.manage");

  if (!can(session, "participants.read")) {
    redirect("/");
  }
  // Tarif-Filter vorbelegen (Links aus den Bussen-Regeln: /participants?tariff=<id>)
  const { tariff } = await searchParams;
  const access = can(session, "access.manage");
  const financeRead = can(session, "finances.read") && featureAccess(session, "finance") !== "none";
  const financeManage = can(session, "fines.manage") && featureAccess(session, "finance") === "full";

  const [participants, templates, roles, tariffs] = await Promise.all([
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?include_former=true&limit=2000"),
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    access ? backendFetchWithSession<RoleRead[]>("/api/roles") : Promise.resolve(null),
    financeRead ? backendFetchWithSession<FineTariffGroup[]>("/api/todo-fines/tariffs") : Promise.resolve(null),
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
              tenantId={session.current_tenant?.id ?? null}
              roles={roles ?? []}
              tariffs={tariffs ?? []}
              permissions={{ access, financeRead, financeManage }}
              initialTariffFilter={tariff ?? null}
            />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
