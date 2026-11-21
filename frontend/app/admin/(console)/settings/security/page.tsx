import { getTranslations } from "next-intl/server";

import { AdminSettingsSecurityView } from "@/components/admin/admin-settings-views";

// Einstellungen › security (1.5.1, Plan §2 G) - nur Anzeige.
export default async function AdminSettingsSecurityPage() {
  const t = await getTranslations("admin.settingsPages.security");
  return (
    <section className="panel section-stack">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
      </div>
      <AdminSettingsSecurityView />
    </section>
  );
}
