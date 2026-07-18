import { AdminTenantManagement } from "@/components/admin/admin-tenant-management";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantSummary } from "@/types/api";

export default async function AdminTenantsPage() {
  const session = await requireAdminSession();
  const tenants = await backendFetchWithSession<AdminTenantSummary[]>("/api/admin/tenants");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminTenantManagement initialTenants={tenants ?? []} />
      </section>
    </AdminShell>
  );
}
