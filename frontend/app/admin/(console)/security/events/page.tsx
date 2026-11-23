import { Suspense } from "react";

import { SecurityEvents } from "@/components/admin/security/security-events";
import { adminIsOwner } from "@/lib/admin/tenant-detail-server";

export default async function AdminSecurityEventsPage() {
  const isOwner = await adminIsOwner();
  return (
    <section className="panel section-stack">
      {/* useSearchParams (Filter in der URL) braucht eine Suspense-Grenze */}
      <Suspense fallback={null}>
        <SecurityEvents canWrite={isOwner} />
      </Suspense>
    </section>
  );
}
