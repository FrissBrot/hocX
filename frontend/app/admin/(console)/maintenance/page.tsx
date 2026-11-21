import { AdminMaintenance } from "@/components/admin/admin-maintenance";
import { backendFetchWithSession } from "@/lib/api/server";
import { MaintenanceOverview } from "@/types/api";

const EMPTY: MaintenanceOverview = { blocking: false, full_active: false, current: [], scheduled: [], history: [], history_total: 0 };

export default async function AdminMaintenancePage() {
  const overview = await backendFetchWithSession<MaintenanceOverview>("/api/admin/maintenance");
  return (
    <>
      <section className="admin-page">
        <AdminMaintenance initialOverview={overview ?? EMPTY} />
      </section>
    </>
  );
}
