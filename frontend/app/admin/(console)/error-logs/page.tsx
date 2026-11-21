import { AdminErrorLog } from "@/components/admin/admin-error-log";
import { backendFetchWithSession } from "@/lib/api/server";
import { AdminTenantPage, SystemErrorLogFilterOptions, SystemErrorLogPage } from "@/types/api";

export default async function AdminErrorLogsPage() {
  const [page, filterOptions, tenants] = await Promise.all([
    backendFetchWithSession<SystemErrorLogPage>("/api/admin/error-logs"),
    backendFetchWithSession<SystemErrorLogFilterOptions>("/api/admin/error-logs/filter-options"),
    // No limit param -> full (unpaginated) list, needed here for the tenant filter dropdown.
    backendFetchWithSession<AdminTenantPage>("/api/admin/tenants"),
  ]);

  return (
    <>
      <section className="panel">
        <AdminErrorLog
          initialPage={page ?? { items: [], total: 0 }}
          initialFilterOptions={filterOptions ?? { error_types: [], sources: [] }}
          tenants={tenants?.items ?? []}
        />
      </section>
    </>
  );
}
