import { MobileTemplates } from "@/components/mobile/areas/mobile-templates";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { protocolTemplateTabs } from "@/components/ui/section-tabs";
import { TemplateBuilder } from "@/components/template/template-builder";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary, TemplateSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function TemplatesPage() {
  const session = await requireSession();
  if (!can(session, "templates.edit")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const [data, cycleConfigs] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTemplates initialTemplates={data ?? []} cycleConfigs={cycleConfigs ?? []} />}
        desktop={
          <>
          <RouteTabs tabs={protocolTemplateTabs(t)} activeHref="/templates" />
          <section className="panel">
            <TemplateBuilder initialTemplates={data ?? []} availableCycleConfigs={cycleConfigs ?? []} canManage={can(session, "templates.manage")} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
