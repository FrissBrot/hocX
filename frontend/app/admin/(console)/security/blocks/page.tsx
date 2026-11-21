import { getTranslations } from "next-intl/server";

import { SecurityBlocks } from "@/components/admin/security/security-blocks";
import { SecurityPageHeader } from "@/components/admin/security/security-page-header";
import { adminIsOwner } from "@/lib/admin/tenant-detail-server";

export default async function AdminSecurityBlocksPage() {
  const [t, isOwner] = await Promise.all([getTranslations("adminSecurity.blocks"), adminIsOwner()]);
  return (
    <section className="panel section-stack">
      <SecurityPageHeader title={t("title")} description={t("description")} />
      <SecurityBlocks canWrite={isOwner} />
    </section>
  );
}
