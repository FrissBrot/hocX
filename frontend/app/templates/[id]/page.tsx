import { AppShell } from "@/components/ui/app-shell";
import { TemplateEditor } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ElementDefinition, TemplateElement, TemplateSummary } from "@/types/api";

export default async function TemplateDetailPage({ params }: { params: { id: string } }) {
  const session = await requireSession();
  const [template, elements, definitions] = await Promise.all([
    backendFetchWithSession<TemplateSummary>(`/api/templates/${params.id}`),
    backendFetchWithSession<TemplateElement[]>(`/api/templates/${params.id}/elements`),
    backendFetchWithSession<ElementDefinition[]>("/api/element-definitions")
  ]);

  if (!template) {
    return (
      <AppShell initialSession={session}>
        <section className="panel">
          <div className="eyebrow">Template Detail</div>
          <h1>Template not found</h1>
          <p className="muted">The requested template could not be loaded from the backend.</p>
        </section>
      </AppShell>
    );
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
        />
      </section>
    </AppShell>
  );
}
