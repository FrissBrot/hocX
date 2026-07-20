import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { TemplateEditor } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, DocumentTemplate, ElementDefinition, EventSummary, ParticipantSummary, StructuredListDefinition, TemplateElement, TemplateSummary } from "@/types/api";

export default async function TemplateDetailPage({ params }: { params: { id: string } }) {
  const session = await requireSession();
  const [template, elements, definitions, events, participants, selectedParticipants, lists, documentTemplates, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary>(`/api/templates/${params.id}`),
    backendFetchWithSession<TemplateElement[]>(`/api/templates/${params.id}/elements`),
    backendFetchWithSession<ElementDefinition[]>("/api/element-definitions"),
    backendFetchWithSession<EventSummary[]>("/api/events"),
    backendFetchWithSession<ParticipantSummary[]>("/api/participants"),
    backendFetchWithSession<ParticipantSummary[]>(`/api/templates/${params.id}/participants`),
    backendFetchWithSession<StructuredListDefinition[]>("/api/lists"),
    backendFetchWithSession<DocumentTemplate[]>("/api/document-templates"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  if (!template) {
    redirect("/templates");
  }

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="eyebrow">Template Detail</div>
        <h1>{template.name}</h1>
        <p className="muted">Choose finished elements here and place them in order. The element structure itself is maintained in the Elements area.</p>
        <TemplateEditor
          initialTemplate={template}
          initialElements={elements ?? []}
          initialDefinitions={definitions ?? []}
          availableEvents={events ?? []}
          availableParticipants={participants ?? []}
          availableLists={lists ?? []}
          initialAssignedParticipants={selectedParticipants ?? []}
          availableDocumentTemplates={documentTemplates ?? []}
          availableCycleConfigs={cycleConfigs ?? []}
        />
      </section>
    </AppShell>
  );
}
