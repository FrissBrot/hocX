import { AdminUserManagement } from "@/components/admin/admin-user-management";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage, AdminUserPage } from "@/types/api";

export default async function AdminUsersPage() {
  const [page, tenants] = await Promise.all([
    backendFetchWithSession<AdminUserPage>("/api/admin/users?limit=50&offset=0"),
    // Full (unpaginated) list - needed for the per-user tenant-role picker, not just the current page.
    backendFetchWithSession<AdminTenantPage>("/api/admin/tenants")
  ]);

  return (
    <>
      <section className="panel">
        <AdminUserManagement initialPage={page ?? { items: [], total: 0 }} allTenants={tenants?.items ?? []} />
      </section>
    </>
  );
}
