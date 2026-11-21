import { getTranslations } from "next-intl/server";

import { AdminMfaSettings } from "@/components/admin/admin-mfa-settings";
import { StatusBanner } from "@/components/ui/status-banner";
import { backendFetchWithSession } from "@/lib/api/server";
import type { UserMfaOverview } from "@/types/api";

// Profil des angemeldeten Plattform-Admins (früher Dialog über /admin/security): Passkeys verwalten.
export default async function AdminAccountPage() {
  const t = await getTranslations("adminShell");
  const overview = await backendFetchWithSession<UserMfaOverview>("/api/admin/mfa");
  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("account.title")}</h1>
          <p className="muted">{t("account.description")}</p>
        </div>
      </div>
      <section className="panel">
        {overview ? <AdminMfaSettings initialOverview={overview} /> : <StatusBanner tone="error" message={t("accountSettingsLoadFailed")} />}
      </section>
    </div>
  );
}
