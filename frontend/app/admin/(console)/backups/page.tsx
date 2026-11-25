import { Suspense } from "react";
import { getTranslations } from "next-intl/server";

import { AdminBackups } from "@/components/admin/admin-backups";
import { StatusBanner } from "@/components/ui/status-banner";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { BackupSettings, BackupStatus } from "@/types/api";

// Reiter, Verlaufsfilter und geöffneter Auftrag stehen in der URL (useSearchParams, daher Suspense).
export default async function AdminBackupsPage() {
  const session = await requireAdminSession();
  const t = await getTranslations("adminBackups");
  const [status, settings] = await Promise.all([
    backendFetchWithSession<BackupStatus>("/api/admin/backups/status"),
    backendFetchWithSession<BackupSettings>("/api/admin/backups/settings"),
  ]);
  return status && settings ? (
    <Suspense fallback={null}>
      <AdminBackups initialStatus={status} initialSettings={settings} isOwner={session.admin?.role === "owner"} />
    </Suspense>
  ) : (
    <section className="panel">
      <StatusBanner tone="error" message={t("loadFailed")} />
    </section>
  );
}
