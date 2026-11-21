import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { SecurityActivity } from "@/components/settings/security-activity";
import { StatusBanner } from "@/components/ui/status-banner";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";
import type { TenantSecurityActivity } from "@/types/admin-security";

// «Sicherheit & Anmeldungen» des aktiven Mandanten (Recht security.read, Standardrolle admin).
// Ohne Recht zurück zur Startseite wie beim Verlauf; Sitzungen beenden nur mit access.manage.
export default async function TenantSecurityPage() {
  const session = await requireSession();
  if (!can(session, "security.read")) {
    redirect("/");
  }
  const [t, tTenant, state] = await Promise.all([
    getTranslations("tenantSettings.security"),
    getTranslations("tenantSettings"),
    backendFetchWithSession<TenantSecurityActivity>("/api/auth-security/activity"),
  ]);
  const content = state ? (
    <SecurityActivity initial={state} canRevoke={can(session, "access.manage")} />
  ) : (
    <StatusBanner tone="error" message={t("loadFailed")} />
  );

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><div className="mobile-section">{content}</div></MobileTenantSettings>}
        desktop={
          <section className="panel">
            <div className="section-stack">
              <div className="page-header">
                <div>
                  <h1 className="page-title">{t("title")}</h1>
                  <p className="muted">{t("description")}</p>
                </div>
              </div>
              {content}
            </div>
          </section>
        }
      />
    </AppShell>
  );
}
