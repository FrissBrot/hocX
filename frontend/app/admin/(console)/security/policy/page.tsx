import { getTranslations } from "next-intl/server";

import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { SecurityPolicyView } from "@/components/admin/security/security-policy";

export default async function AdminSecurityPolicyPage() {
  const t = await getTranslations("adminSecurity.policy");
  return (
    <section className="panel section-stack">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      <SecurityPolicyView />
    </section>
  );
}
