import { getTranslations } from "next-intl/server";

import { AdminStorage } from "@/components/admin/admin-storage";
import { AdminShell } from "@/components/ui/admin-shell";
import { StatusBanner } from "@/components/ui/status-banner";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { StorageOverview } from "@/types/api";

export default async function AdminStoragePage() {
  const session = await requireAdminSession();
  const t = await getTranslations("adminStorage");
  const overview = await backendFetchWithSession<StorageOverview>("/api/admin/storage/overview");
  return (
    <AdminShell session={session}>
      <section className="admin-page">
        {overview ? <AdminStorage initialOverview={overview} /> : <StatusBanner tone="error" message={t("loadFailed")} />}
      </section>
    </AdminShell>
  );
}
