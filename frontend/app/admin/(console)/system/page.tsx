import { AdminSystemStatus } from "@/components/admin/admin-system-status";
import { backendFetchWithSession } from "@/lib/api/server";
import { SystemStatus } from "@/types/api";

export default async function AdminSystemPage() {
  const status = await backendFetchWithSession<SystemStatus>("/api/admin/system-status");

  return (
    <>
      <section className="admin-page">
        <AdminSystemStatus initialStatus={status ?? { snapshot: null, stale: true, problems: [], events: [], overload: [] }} />
      </section>
    </>
  );
}
