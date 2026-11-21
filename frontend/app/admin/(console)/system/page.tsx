import { AdminSystemHistory } from "@/components/admin/admin-operations-history";
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
      {/* 1.5.1: Verläufe Datenbank und Redis (Ressourcen-Stichproben), getrennt vom Live-Status */}
      <section className="admin-page">
        <AdminSystemHistory />
      </section>
    </>
  );
}
