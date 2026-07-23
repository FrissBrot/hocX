import { redirect } from "next/navigation";

import { TenantSettingsManager } from "@/components/settings/tenant-settings-manager";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { TenantSummary } from "@/types/api";

export default async function TenantSettingsPage({ searchParams }: { searchParams: { tenantId?: string } }) {
  const session = await requireSession();

  // /api/tenants is already scoped to tenants the current user administers.
  const manageableTenants = await backendFetchWithSession<TenantSummary[]>("/api/tenants");
  if (!manageableTenants || manageableTenants.length === 0) {
    redirect("/");
  }

  const requestedId = searchParams.tenantId ? Number(searchParams.tenantId) : session.current_tenant?.id;
  const tenant = manageableTenants.find((t) => t.id === requestedId) ?? manageableTenants[0];

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <TenantSettingsManager initialTenant={tenant} />
      </section>
    </AppShell>
  );
}
