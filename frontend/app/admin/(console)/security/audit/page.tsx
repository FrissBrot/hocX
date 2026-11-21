import { Suspense } from "react";

import { AdminAuditLog } from "@/components/admin/admin-audit-log";
import { SecurityTabs } from "@/components/admin/security/security-tabs";
import { backendFetchWithSession } from "@/lib/api/server";
import { AuditLogPage } from "@/types/api";

// Filter stehen in der URL (useServerTable); die erste Seite lädt der Server ungefiltert, der Client
// lädt sofort mit den Filtern aus der Adresse nach. Keine Mandantenliste mehr (Remote-Picker).
export default async function AdminAuditPage() {
  const page = await backendFetchWithSession<AuditLogPage>("/api/admin/audit-log");
  return (
    <section className="panel section-stack">
      <SecurityTabs />
      <Suspense fallback={null}>
        <AdminAuditLog initialPage={page ?? { items: [], total: 0 }} />
      </Suspense>
    </section>
  );
}
