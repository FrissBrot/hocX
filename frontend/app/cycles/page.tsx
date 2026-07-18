import { CycleConfigManager } from "@/components/cycles/cycle-config-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { CycleConfigSummary } from "@/types/api";

export default async function CyclesPage() {
  const session = await requireSession();
  const configs = (await backendFetchWithSession<CycleConfigSummary[]>("/api/cycle-configs")) ?? [];

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <CycleConfigManager initialConfigs={configs} />
      </section>
    </AppShell>
  );
}
