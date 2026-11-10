import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { DocumentVerificationSettings, type DocumentVerificationState } from "@/components/settings/document-verification-settings";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { tenantSettingsTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";

// Echtheitsprüfung (Prüfseite, Verifizierung durch hocX). Die API arbeitet immer auf dem aktiven
// Mandanten, daher hier kein ?tenantId wie bei den übrigen Tabs.
export default async function TenantVerificationPage() {
  const session = await requireSession();
  if (!can(session, "settings.manage")) {
    redirect("/");
  }
  const [t, tTenant, state] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    backendFetchWithSession<DocumentVerificationState>("/api/document-verification"),
  ]);
  const content = state ? <DocumentVerificationSettings initialState={state} /> : null;

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
              <RouteTabs tabs={tenantSettingsTabs(t)} activeHref="/tenant-settings/verification" variant="pill" />
              {content}
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
