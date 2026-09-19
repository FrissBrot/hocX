import { redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { TEMPLATE_TABS } from "@/components/ui/section-tabs";
import { TemplateBuilder } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, TemplateSummary } from "@/types/api";

export default async function TemplatesPage() {
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const [data, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  return (
    <AppShell initialSession={session}>
      <RouteTabs tabs={TEMPLATE_TABS} activeHref="/templates" />
      <section className="panel">
        <TemplateBuilder initialTemplates={data ?? []} availableCycleConfigs={cycleConfigs ?? []} />
      </section>
    </AppShell>
  );
}
