import { AdminAuditLog } from "@/components/admin/admin-audit-log";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage, AuditLogPage } from "@/types/api";

export default async function AdminAuditPage() {
  const session = await requireAdminSession();
  const [page, tenants] = await Promise.all([
    backendFetchWithSession<AuditLogPage>("/api/admin/audit-log"),
    backendFetchWithSession<AdminTenantPage>("/api/admin/tenants"),
  ]);

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminAuditLog initialPage={page ?? { items: [], total: 0 }} tenants={tenants?.items ?? []} />
      </section>
    </AdminShell>
  );
}
