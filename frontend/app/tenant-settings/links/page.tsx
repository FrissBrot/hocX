import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PublicLinksOverview } from "@/components/settings/public-links-overview";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { tenantSettingsTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { PublicLinkItem } from "@/types/api";
import { can } from "@/lib/permissions";

// Zugangslinks: alle gerade gültigen Wege ohne Anmeldung zu Daten des Vereins (app/public_links).
export default async function TenantPublicLinksPage() {
  const session = await requireSession();
  if (!can(session, "settings.manage")) {
    redirect("/");
  }
  const [t, tTenant, state] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    backendFetchWithSession<PublicLinkItem[]>("/api/public-links"),
  ]);
  const content = <PublicLinksOverview links={state ?? []} />;
  const mobileContent = <PublicLinksOverview links={state ?? []} mobile />;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><div className="mobile-section">{mobileContent}</div></MobileTenantSettings>}
        desktop={
          <>
          <section className="panel">
            <div className="section-stack">
              <div className="page-header">
                <div>
                  <h1 className="page-title">{tTenant("pageTitle")}</h1>
                  <p className="muted">{tTenant("pageDescription", { tenant: session.current_tenant?.name ?? "" })}</p>
                </div>
              </div>
              <RouteTabs tabs={tenantSettingsTabs(t)} activeHref="/tenant-settings/links" variant="pill" />
              {content}
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
