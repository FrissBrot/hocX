import { AdminTenantManagement } from "@/components/admin/admin-tenant-management";
import { tenantListQuery, tenantViewFromParams } from "@/lib/admin/tenant-list";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminPlan, AdminTenantPage } from "@/types/api";

type SearchParams = { plan?: string; q?: string; sort?: string; dir?: string; status?: string; storage_min_ratio?: string };

export default async function AdminTenantsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const plan = params.plan ?? "";
  const view = tenantViewFromParams(params);
  const query = tenantListQuery(view, plan);
  query.set("limit", "50");
  query.set("offset", "0");
  const [page, plans] = await Promise.all([
    backendFetchWithSession<AdminTenantPage>(`/api/admin/tenants?${query.toString()}`),
    backendFetchWithSession<AdminPlan[]>("/api/admin/plans"),
  ]);

  return (
    <AdminTenantManagement
      initialPage={page ?? { items: [], total: 0 }}
      initialPlans={plans ?? []}
      initialPlanFilter={plan}
      initialView={view}
    />
  );
}
