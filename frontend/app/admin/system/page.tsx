import { AdminSystemStatus } from "@/components/admin/admin-system-status";
import { AdminShell } from "@/components/ui/admin-shell";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { SystemStatus } from "@/types/api";

export default async function AdminSystemPage() {
  const session = await requireAdminSession();
  const status = await backendFetchWithSession<SystemStatus>("/api/admin/system-status");

  return (
    <AdminShell session={session}>
      <section className="panel">
        <AdminSystemStatus initialStatus={status ?? { snapshot: null, stale: true, problems: [], events: [] }} />
      </section>
    </AdminShell>
  );
}
