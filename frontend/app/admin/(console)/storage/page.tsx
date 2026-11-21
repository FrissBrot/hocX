import { getTranslations } from "next-intl/server";

import { AdminStorageOccupancy } from "@/components/admin/admin-operations-history";
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
      {/* 1.5.1: Belegung aus dem täglichen Snapshot (keine Live-Summe) */}
      <section className="admin-page">
        <AdminStorageOccupancy />
      </section>
    </>
  );
}
