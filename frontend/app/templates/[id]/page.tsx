import { MobileTemplateDetail } from "@/components/mobile/areas/mobile-templates";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { TemplateEditor } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, DocumentStyle, ElementDefinition, EventSummary, ParticipantSummary, StructuredListDefinition, TemplateElement, TemplateSummary } from "@/types/api";

export default async function TemplateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const [template, elements, definitions, events, participants, selectedParticipants, lists, documentStyles, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary>(`/api/templates/${id}`),
    backendFetchWithSession<TemplateElement[]>(`/api/templates/${id}/elements`),
    backendFetchWithSession<ElementDefinition[]>("/api/element-definitions"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants?limit=2000"),
    backendFetchWithSession<ParticipantSummary[]>(`/api/templates/${id}/participants`),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<DocumentStyle[]>("/api/document-styles"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  if (!template) {
    redirect("/templates");
  }

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTemplateDetail initialTemplate={template} elements={elements ?? []} participants={participants ?? []} initialAssigned={selectedParticipants ?? []} documentStyles={documentStyles ?? []} cycleConfigs={cycleConfigs ?? []} />}
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
              availableDocumentStyles={documentStyles ?? []}
              availableCycleConfigs={cycleConfigs ?? []}
            />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
