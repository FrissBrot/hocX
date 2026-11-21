import { AdminErrorLog } from "@/components/admin/admin-error-log";
import { backendFetchWithSession } from "@/lib/api/server";
import { SystemErrorLogFilterOptions, SystemErrorLogPage } from "@/types/api";

export default async function AdminErrorLogsPage() {
  // Mandantenfilter per Remote-Picker (1.5.1) - keine ganze Mandantenliste mehr.
  const [page, filterOptions] = await Promise.all([
    backendFetchWithSession<SystemErrorLogPage>("/api/admin/error-logs"),
    backendFetchWithSession<SystemErrorLogFilterOptions>("/api/admin/error-logs/filter-options"),
  ]);

  return (
    <section className="panel">
      <AdminErrorLog initialPage={page ?? { items: [], total: 0 }} initialFilterOptions={filterOptions ?? { error_types: [], sources: [] }} />
    </section>
  );
}
