import { getTranslations } from "next-intl/server";

import { AdminSettingsIntegrationsView } from "@/components/admin/admin-settings-views";

// Einstellungen › integrations (1.5.1, Plan §2 G) - nur Anzeige.
export default async function AdminSettingsIntegrationsPage() {
  const t = await getTranslations("admin.settingsPages.integrations");
  return (
    <section className="panel section-stack">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
      </div>
      <AdminSettingsIntegrationsView />
    </section>
  );
}
