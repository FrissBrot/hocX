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
        <div className="eyebrow">Administration</div>
        <h1>Mandantenverwaltung</h1>
        <p className="muted">
          Bearbeite nur jene Mandanten, in denen du wirklich Administrator bist. Profilbild und Name bleiben so klar getrennt von der Benutzerverwaltung.
        </p>
        <TenantManagement initialTenants={tenants ?? []} canCreateTenant={!!session.user?.is_superadmin} />
      </section>
    </AppShell>
  );
}
