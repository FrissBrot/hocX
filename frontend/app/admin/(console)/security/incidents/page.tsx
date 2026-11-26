import { Suspense } from "react";

import { SecurityIncidents } from "@/components/admin/security/security-incidents";

// Vorfälle (1.7): Filter, Ansicht und geöffneter Vorfall stehen in der URL (useSearchParams braucht
// eine Suspense-Grenze).
export default function AdminSecurityIncidentsPage() {
  return (
    <section className="panel section-stack admin-security-panel">
      <Suspense fallback={null}>
        <SecurityIncidents />
      </Suspense>
    </section>
  );
}
