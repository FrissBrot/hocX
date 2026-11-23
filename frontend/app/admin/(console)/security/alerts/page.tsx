import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { SecurityAlertRules } from "@/components/admin/security/security-alert-rules";
import { SecurityAlertsView } from "@/components/admin/security/security-alerts";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { adminIsOwner } from "@/lib/admin/tenant-detail-server";

// Alarmregeln (1.6, vorher «Warnungen»): Regeln mit Messwerten oben, ausgelöste Warnungen mit
// Quittieren (Notiz) darunter - Letzteres wird in 1.7 zum Vorfall-Status.
export default async function AdminSecurityAlertsPage() {
  const [t, isOwner] = await Promise.all([getTranslations("adminSecurity.alerts"), adminIsOwner()]);
  return (
    <section className="panel section-stack">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      {/* useSearchParams (Regel und Zustand in der URL) braucht eine Suspense-Grenze */}
      <Suspense fallback={null}>
        <SecurityAlertRules />
      </Suspense>
      <SecurityAlertsView canWrite={isOwner} />
    </section>
  );
}
