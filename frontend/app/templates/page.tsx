import { AppShell } from "@/components/ui/app-shell";
import { TemplateBuilder } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, TemplateSummary } from "@/types/api";

export default async function TemplatesPage() {
  const session = await requireSession();
  const [data, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <TemplateBuilder initialTemplates={data ?? []} availableCycleConfigs={cycleConfigs ?? []} />
      </section>
    </AppShell>
  );
}
