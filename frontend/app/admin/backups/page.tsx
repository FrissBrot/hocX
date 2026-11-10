import { getTranslations } from "next-intl/server";

import { AdminBackups } from "@/components/admin/admin-backups";
import { AdminShell } from "@/components/ui/admin-shell";
import { StatusBanner } from "@/components/ui/status-banner";
import { requireAdminSession } from "@/lib/api/admin-server";
import { backendFetchWithSession } from "@/lib/api/server";
import { BackupSettings, BackupStatus } from "@/types/api";

export default async function AdminBackupsPage() {
  const session = await requireAdminSession();
  const t = await getTranslations("adminBackups");
  const [status, settings] = await Promise.all([
    backendFetchWithSession<BackupStatus>("/api/admin/backups/status"),
    backendFetchWithSession<BackupSettings>("/api/admin/backups/settings"),
  ]);
  return (
    <AdminShell session={session}>
      <section className="panel">
        {status && settings ? (
          <AdminBackups initialStatus={status} initialSettings={settings} isOwner={session.admin?.role === "owner"} />
        ) : (
          <StatusBanner tone="error" message={t("loadFailed")} />
        )}
      </section>
    </AdminShell>
  );
}
