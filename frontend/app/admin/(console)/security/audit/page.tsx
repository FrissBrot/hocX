import { AdminAuditLog } from "@/components/admin/admin-audit-log";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage, AuditLogPage } from "@/types/api";

export default async function AdminAuditPage() {
  const [page, tenants] = await Promise.all([
    backendFetchWithSession<AuditLogPage>("/api/admin/audit-log"),
    backendFetchWithSession<AdminTenantPage>("/api/admin/tenants"),
  ]);

  return (
    <>
      <section className="panel">
        <AdminAuditLog initialPage={page ?? { items: [], total: 0 }} tenants={tenants?.items ?? []} />
      </section>
    </>
  );
}
