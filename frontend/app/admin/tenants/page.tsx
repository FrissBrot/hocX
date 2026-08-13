import { AdminTenantManagement } from "@/components/admin/admin-tenant-management";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage } from "@/types/api";

export default async function AdminTenantsPage() {
  const session = await requireAdminSession();
  const page = await backendFetchWithSession<AdminTenantPage>("/api/admin/tenants?limit=50&offset=0");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminTenantManagement initialPage={page ?? { items: [], total: 0 }} />
      </section>
    </AdminShell>
  );
}
