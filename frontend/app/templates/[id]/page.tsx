import { AppShell } from "@/components/ui/app-shell";
import { TemplateEditor } from "@/components/template/template-builder";
import { backendFetch } from "@/lib/api/client";
import { ElementDefinition, TemplateElement, TemplateSummary } from "@/types/api";

export default async function TemplateDetailPage({ params }: { params: { id: string } }) {
  const [template, elements, definitions] = await Promise.all([
    backendFetch<TemplateSummary>(`/api/templates/${params.id}`),
    backendFetch<TemplateElement[]>(`/api/templates/${params.id}/elements`),
    backendFetch<ElementDefinition[]>("/api/element-definitions")
  ]);

  if (!template) {
    return (
      <AppShell>
        <section className="panel">
          <div className="eyebrow">Template Detail</div>
          <h1>Template not found</h1>
          <p className="muted">The requested template could not be loaded from the backend.</p>
        </section>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Template Detail</div>
        <h1>{template.name}</h1>
        <p className="muted">Manage template metadata, assign element definitions and control ordering and sections.</p>
        <TemplateEditor
          initialTemplate={template}
          initialElements={elements ?? []}
          initialDefinitions={definitions ?? []}
        />
      </section>
    </AppShell>
  );
}
