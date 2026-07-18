import { AdminUserManagement } from "@/components/admin/admin-user-management";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantSummary, UserSummary } from "@/types/api";

export default async function AdminUsersPage() {
  const session = await requireAdminSession();
  const [users, tenants] = await Promise.all([
    backendFetchWithSession<UserSummary[]>("/api/admin/users"),
    backendFetchWithSession<AdminTenantSummary[]>("/api/admin/tenants")
  ]);

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminUserManagement initialUsers={users ?? []} allTenants={tenants ?? []} />
      </section>
    </AdminShell>
  );
}
