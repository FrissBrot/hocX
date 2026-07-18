import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantSummary, UserSummary } from "@/types/api";

export default async function AdminDashboardPage() {
  const session = await requireAdminSession();
  const [tenants, users] = await Promise.all([
    backendFetchWithSession<AdminTenantSummary[]>("/api/admin/tenants"),
    backendFetchWithSession<UserSummary[]>("/api/admin/users"),
  ]);

  const tenantCount = tenants?.length ?? 0;
  const userCount = users?.length ?? 0;
  const activeLoginCount = (users ?? []).filter((user) => user.login_enabled).length;

  return (
    <AdminShell session={session}>
      <section className="panel">
        <div className="eyebrow">Übersicht</div>
        <h1>Dashboard</h1>
        <div className="three-col">
          <div className="card">
            <div className="eyebrow">Mandanten</div>
            <strong style={{ fontSize: "2rem" }}>{tenantCount}</strong>
          </div>
          <div className="card">
            <div className="eyebrow">Benutzer gesamt</div>
            <strong style={{ fontSize: "2rem" }}>{userCount}</strong>
          </div>
          <div className="card">
            <div className="eyebrow">Mit aktivem Login</div>
            <strong style={{ fontSize: "2rem" }}>{activeLoginCount}</strong>
          </div>
        </div>
      </section>
    </AdminShell>
  );
}
