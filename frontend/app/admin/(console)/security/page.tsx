import { getTranslations } from "next-intl/server";

import { SecurityOverview } from "@/components/admin/security/security-overview";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";

// Sicherheitsbereich (Plan §2 D): Übersicht über den Anmeldeschutz der Plattform. Das persönliche
// Profil liegt seit dem Redesign unter /admin/account.
export default async function AdminSecurityPage() {
  const t = await getTranslations("adminSecurity.overview");
  return (
    <section className="panel section-stack">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      <SecurityOverview />
    </section>
  );
}
