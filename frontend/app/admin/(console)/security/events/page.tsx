import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { SecurityEvents } from "@/components/admin/security/security-events";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";

export default async function AdminSecurityEventsPage() {
  const t = await getTranslations("adminSecurity.events");
  return (
    <section className="panel section-stack">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      {/* useSearchParams (Filter in der URL) braucht eine Suspense-Grenze */}
      <Suspense fallback={null}>
        <SecurityEvents />
      </Suspense>
    </section>
  );
}
