import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PrivacySettings, type PrivacySettingsState } from "@/components/settings/privacy-settings";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { tenantSettingsTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";

// Datenschutz-Einstellungen des aktiven Mandanten (nur Mandanten-Admins).
export default async function TenantPrivacyPage() {
  const session = await requireSession();
  if (!can(session, "settings.manage")) {
    redirect("/");
  }
  const [t, tTenant, state] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    backendFetchWithSession<PrivacySettingsState>("/api/privacy-settings"),
  ]);
  const content = state ? <PrivacySettings initialState={state} /> : null;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><div className="mobile-section">{content}</div></MobileTenantSettings>}
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
              <RouteTabs tabs={tenantSettingsTabs(t)} activeHref="/tenant-settings/privacy" variant="pill" />
              {content}
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
