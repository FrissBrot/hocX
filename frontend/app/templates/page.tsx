import { MobileTemplates } from "@/components/mobile/areas/mobile-templates";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { templateAreaTabs } from "@/components/ui/section-tabs";
import { TemplateBuilder } from "@/components/template/template-builder";
import { TemplateLibrary } from "@/components/documents/template-library";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import type { Capabilities } from "@/lib/documents/api";
import { CycleConfigSummary, TemplateSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function TemplatesPage() {
  const session = await requireSession();
  if (!can(session, "templates.edit")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const [data, cycleConfigs, capabilities] = await Promise.all([
    backendFetchWithSession<TemplateSummary[]>("/api/templates"),
    backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs"),
    backendFetchWithSession<Capabilities>("/api/document-studio/capabilities"),
  ]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTemplates initialTemplates={data ?? []} cycleConfigs={cycleConfigs ?? []} />}
        desktop={
          <>
          <RouteTabs tabs={templateAreaTabs(t, can(session, "templates.manage"))} activeHref="/templates" />
          <section className="panel">
            <TemplateBuilder initialTemplates={data ?? []} availableCycleConfigs={cycleConfigs ?? []} canManage={can(session, "templates.manage")} />
          </section>
          {capabilities ? (
            <section className="panel">
              <TemplateLibrary capabilities={capabilities} scope="session" />
            </section>
          ) : null}
          </>
        }
      />
    </AppShell>
  );
}
