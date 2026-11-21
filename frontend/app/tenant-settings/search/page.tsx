import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { SearchSynonymsSettings, type SearchSynonyms } from "@/components/settings/search-synonyms-settings";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";

// Suche: mandanteneigene Synonyme für Fotos und Ablage (services/search_synonyms.py).
export default async function TenantSearchSettingsPage() {
  const session = await requireSession();
  if (!can(session, "settings.manage")) {
    redirect("/");
  }
  const [t, tTenant, tSearch, data] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    getTranslations("tenantSettings.searchSynonyms"),
    backendFetchWithSession<SearchSynonyms>("/api/search-synonyms"),
  ]);
  const initial = data ?? { groups: [], builtin: [] };

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={
          <MobileTenantSettings title={tTenant("pageTitle")}>
            <div className="mobile-section">
              <SearchSynonymsSettings initial={initial} />
            </div>
          </MobileTenantSettings>
        }
        desktop={
          <section className="panel">
            <div className="section-stack">
              <div className="page-header">
                <div>
                  <div className="eyebrow">{tSearch("eyebrow")}</div>
                  <h1 className="page-title">{t("searchSynonyms")}</h1>
                  <p className="muted">{tSearch("intro")}</p>
                </div>
              </div>
              <SearchSynonymsSettings initial={initial} />
            </div>
          </section>
        }
      />
    </AppShell>
  );
}
