import { redirect } from "next/navigation";

import { TenantManagement } from "@/components/tenants/tenant-management";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { TenantSummary } from "@/types/api";

export default async function TenantsPage() {
  const session = await requireSession();
  const canAdmin = session.user?.is_superadmin || session.current_role === "admin";

  if (!canAdmin) {
    redirect("/");
  }

  const tenants = await backendFetchWithSession<TenantSummary[]>("/api/tenants");

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <TenantManagement initialTenants={tenants ?? []} canCreateTenant={!!session.user?.is_superadmin} />
      </section>
    </AppShell>
  );
}
