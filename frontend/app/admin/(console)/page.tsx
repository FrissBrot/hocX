import { AdminOverview } from "@/components/admin/admin-overview";
import { backendFetchWithSession } from "@/lib/api/server";
import type { AdminOverview as Overview } from "@/types/admin-overview";

// Übersicht (Plan §3): ein Request für Status, Kennzahlen, «Zu erledigen» und Feed - nur Aggregate,
// serverseitig 60 s gecacht. Diagramme lädt die Client-Komponente nach.
export default async function AdminDashboardPage() {
  const overview = await backendFetchWithSession<Overview>("/api/admin/overview");
  return <AdminOverview initial={overview} />;
}
