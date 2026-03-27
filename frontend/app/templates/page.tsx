import { AppShell } from "@/components/ui/app-shell";
import { TemplateBuilder } from "@/components/template/template-builder";
import { backendFetch } from "@/lib/api/client";
import { TemplateSummary } from "@/types/api";

export default async function TemplatesPage() {
  const data = await backendFetch<TemplateSummary[]>("/api/templates");

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Template Builder</div>
        <h1>Template list</h1>
        <p className="muted">Create templates and jump straight into the structure editor.</p>
        <TemplateBuilder initialTemplates={data ?? []} />
      </section>
    </AppShell>
  );
}
