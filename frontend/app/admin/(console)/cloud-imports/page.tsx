import { getTranslations } from "next-intl/server";

import { AdminCloudImports, type AdminImportOverview } from "@/components/admin/admin-cloud-imports";
import { StatusBanner } from "@/components/ui/status-banner";
import { backendFetchWithSession } from "@/lib/api/server";

export default async function AdminCloudImportsPage() {
  const t = await getTranslations("admin.cloudImports");
  const overview = await backendFetchWithSession<AdminImportOverview>("/api/admin/cloud-imports");
  return (
    <section className="admin-page">
      {overview ? <AdminCloudImports initialOverview={overview} /> : <StatusBanner tone="error" message={t("loadFailed")} />}
    </section>
  );
}
