import { MobileCycles } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { redirect } from "next/navigation";

import { CycleConfigManager } from "@/components/cycles/cycle-config-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary } from "@/types/api";

export default async function CyclesPage() {
  const session = await requireSession();
  if (session.current_role !== "admin") {
    redirect("/");
  }
  const configs = (await backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs")) ?? [];

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileCycles initialConfigs={configs} />}
        desktop={
          <>
          <section className="panel">
            <CycleConfigManager initialConfigs={configs} />
          </section>
          </>
        }
      />
    </AppShell>
  );
}
