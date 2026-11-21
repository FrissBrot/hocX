import { getTranslations } from "next-intl/server";

import { SecurityAlertsView } from "@/components/admin/security/security-alerts";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";

export default async function AdminSecurityAlertsPage() {
  const t = await getTranslations("adminSecurity.alerts");
  return (
    <section className="panel section-stack">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      <SecurityAlertsView />
    </section>
  );
}
