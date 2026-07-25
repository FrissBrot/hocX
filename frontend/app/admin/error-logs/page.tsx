import { AdminErrorLog } from "@/components/admin/admin-error-log";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantSummary, SystemErrorLogFilterOptions, SystemErrorLogPage } from "@/types/api";

export default async function AdminErrorLogsPage() {
  const session = await requireAdminSession();
  const [page, filterOptions, tenants] = await Promise.all([
    backendFetchWithSession<SystemErrorLogPage>("/api/admin/error-logs"),
    backendFetchWithSession<SystemErrorLogFilterOptions>("/api/admin/error-logs/filter-options"),
    backendFetchWithSession<AdminTenantSummary[]>("/api/admin/tenants"),
  ]);

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminErrorLog
          initialPage={page ?? { items: [], total: 0 }}
          initialFilterOptions={filterOptions ?? { error_types: [], sources: [] }}
          tenants={tenants ?? []}
        />
      </section>
    </AdminShell>
  );
}
