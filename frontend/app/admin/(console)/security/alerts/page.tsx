import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { SecurityAlertRules } from "@/components/admin/security/security-alert-rules";
import { SecurityAlertsView } from "@/components/admin/security/security-alerts";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";

// Alarmregeln (1.6, vorher «Warnungen»): Regeln mit Messwerten oben, ausgelöste Warnungen mit
// ihrem Vorfall darunter (1.6: Vorfall-Status statt Quittung).
export default async function AdminSecurityAlertsPage() {
  const t = await getTranslations("adminSecurity.alerts");
  return (
    <section className="panel section-stack admin-security-panel">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      {/* useSearchParams (Regel und Zustand in der URL) braucht eine Suspense-Grenze */}
      <Suspense fallback={null}>
        <SecurityAlertRules />
      </Suspense>
      <SecurityAlertsView />
    </section>
  );
}
