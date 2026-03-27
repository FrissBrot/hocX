import { AppShell } from "@/components/ui/app-shell";
import { TemplateList } from "@/components/template/template-list";
import { backendFetch } from "@/lib/api/client";

type TemplateSummary = {
  id: number;
  name: string;
  version: number;
  status: string;
};

export default async function TemplatesPage() {
  const data = await backendFetch<TemplateSummary[]>("/api/templates");

  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Template Builder</div>
        <h1>Template list</h1>
        <p className="muted">The current starter exposes template endpoints and a UI shell for the builder flow.</p>
        <TemplateList
          items={
            data ?? [
              { id: 1, name: "Default protocol template", version: 1, status: "active" },
              { id: 2, name: "Camp retrospective", version: 1, status: "draft-ui" }
            ]
          }
        />
      </section>
    </AppShell>
  );
}

