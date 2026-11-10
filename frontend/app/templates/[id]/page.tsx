import { MobileTemplateDetail } from "@/components/mobile/areas/mobile-templates";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { TemplateEditor } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, EventSummary, FinanceAccount, ParticipantSummary, StructuredListDefinition, TemplateElement, TemplateSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function TemplateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  // Schreibende passen Traktanden und Gestaltung an; Einstellungen bleiben Admins vorbehalten
  const canManage = can(session, "templates.manage");
  if (!can(session, "templates.edit")) {
    redirect("/");
  }
  const [template, elements, events, participants, selectedParticipants, lists, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary>(`/api/templates/${id}`),
    backendFetchWithSession<TemplateElement[]>(`/api/templates/${id}/elements`),
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=2000"),
    backendFetchWithSession<ParticipantSummary[]>(`/api/templates/${id}/participants`),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  if (!template) {
    redirect("/templates");
  }
  // Bussentarif je Vorlage nur mit gebuchten Finanzen (FAR-002).
  const hasFinance = session.current_tenant?.enabled_features?.includes("finance") ?? false;
  const financeAccounts = hasFinance ? (await backendFetchWithSession<FinanceAccount[]>("/api/finance/accounts") ?? []) : null;
  const knownEventTags = Array.from(new Set((events ?? []).map((event) => (event.tag ?? "").trim()).filter((tag) => tag.length > 0))).sort((left, right) => left.localeCompare(right));

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTemplateDetail initialTemplate={template} elements={elements ?? []} participants={participants ?? []} initialAssigned={selectedParticipants ?? []} cycleConfigs={cycleConfigs ?? []} />}
        desktop={
          <>
          <section className="panel session-studio-panel">
            <TemplateEditor
              initialTemplate={template}
              initialElements={elements ?? []}
              canManage={canManage}
              knownEventTags={knownEventTags}
              availableEvents={events ?? []}
              availableParticipants={participants ?? []}
              availableLists={lists ?? []}
              initialAssignedParticipants={selectedParticipants ?? []}
              availableCycleConfigs={cycleConfigs ?? []}
              financeAccounts={financeAccounts}
            />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
