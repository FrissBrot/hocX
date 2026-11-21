import { Suspense } from "react";

import { AdminAnalytics } from "@/components/admin/admin-analytics";
import { requireAdminSession } from "@/lib/api/admin-server";

// Analysen (Admin-Redesign Phase D): Verläufe aus dem täglichen Kennzahlen-Rollup. Die Daten lädt
// die Client-Komponente je Tab und Zeitraum; Nutzung und Fehler nur für Owner (Backend prüft).
export default async function AdminAnalyticsPage() {
  const session = await requireAdminSession();
  const isOwner = session.admin?.role === "owner"; // rbac-ok: Plattform-Admin-Rolle (owner/support), nur Benutzerführung - Backend prüft require_admin_owner
  return (
    <section className="admin-page">
      <Suspense>
        <AdminAnalytics isOwner={isOwner} />
      </Suspense>
    </section>
  );
}
