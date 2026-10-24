import { MobileTemplateDetail } from "@/components/mobile/areas/mobile-templates";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { TemplateEditor } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, ElementDefinition, EventSummary, FinanceAccount, ParticipantSummary, StructuredListDefinition, TemplateElement, TemplateSummary } from "@/types/api";

export default async function TemplateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const [template, elements, definitions, events, participants, selectedParticipants, lists, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary>(`/api/templates/${id}`),
    backendFetchWithSession<TemplateElement[]>(`/api/templates/${id}/elements`),
    backendFetchWithSession<ElementDefinition[]>("/api/element-definitions"),
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

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTemplateDetail initialTemplate={template} elements={elements ?? []} participants={participants ?? []} initialAssigned={selectedParticipants ?? []} cycleConfigs={cycleConfigs ?? []} />}
        desktop={
          <>
          <section className="panel">
            <TemplateEditor
              initialTemplate={template}
              initialElements={elements ?? []}
              initialDefinitions={definitions ?? []}
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
