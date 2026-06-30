import { AppShell } from "@/components/ui/app-shell";
import { TemplateBuilder } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { TemplateSummary } from "@/types/api";

export default async function TemplatesPage() {
  const session = await requireSession();
  const data = await backendFetchWithSession<TemplateSummary[]>("/api/templates");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <TemplateBuilder initialTemplates={data ?? []} />
      </section>
    </AppShell>
  );
}
