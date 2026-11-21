import { getTranslations } from "next-intl/server";

import { AdminStorage } from "@/components/admin/admin-storage";
import { StatusBanner } from "@/components/ui/status-banner";
import { backendFetchWithSession } from "@/lib/api/server";
import { StorageOverview } from "@/types/api";

export default async function AdminStoragePage() {
  const t = await getTranslations("adminStorage");
  const overview = await backendFetchWithSession<StorageOverview>("/api/admin/storage/overview");
  return (
    <>
      <section className="admin-page">
        {overview ? <AdminStorage initialOverview={overview} /> : <StatusBanner tone="error" message={t("loadFailed")} />}
      </section>
    </>
  );
}
