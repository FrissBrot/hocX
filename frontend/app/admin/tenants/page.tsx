import { AdminTenantManagement } from "@/components/admin/admin-tenant-management";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminPlan, AdminTenantPage } from "@/types/api";

export default async function AdminTenantsPage({ searchParams }: { searchParams: Promise<{ plan?: string }> }) {
  const session = await requireAdminSession();
  const { plan } = await searchParams;
  const planQuery = plan ? `&plan=${encodeURIComponent(plan)}` : "";
  const [page, plans] = await Promise.all([
    backendFetchWithSession<AdminTenantPage>(`/api/admin/tenants?limit=50&offset=0${planQuery}`),
    backendFetchWithSession<AdminPlan[]>("/api/admin/plans"),
  ]);

  return (
    <AdminShell session={session}>
      <AdminTenantManagement initialPage={page ?? { items: [], total: 0 }} initialPlans={plans ?? []} initialPlanFilter={plan ?? ""} />
    </AdminShell>
  );
}
