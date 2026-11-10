import { MobileCycles } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { CycleConfigManager } from "@/components/cycles/cycle-config-manager";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { workflowTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary } from "@/types/api";
import { can } from "@/lib/permissions";

export default async function CyclesPage() {
  const session = await requireSession();
  if (!can(session, "templates.manage")) {
    redirect("/");
  }
  const t = await getTranslations("nav");
  const configs = (await backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs")) ?? [];

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileCycles initialConfigs={configs} />}
        desktop={
          <>
          <RouteTabs tabs={workflowTabs(t)} activeHref="/cycles" />
          <section className="panel">
            <CycleConfigManager initialConfigs={configs} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
