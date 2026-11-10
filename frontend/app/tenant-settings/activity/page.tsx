import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { ActivityLog } from "@/components/settings/activity-log";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { tenantSettingsTabs } from "@/components/ui/section-tabs";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ActivityPage } from "@/types/api";
import { can } from "@/lib/permissions";

// Verlauf des aktiven Mandanten (nur Mandanten-Admins, Datenschutz-Audit PRIV-013).
export default async function TenantActivityPage() {
  const session = await requireSession();
  if (!can(session, "settings.manage")) {
    redirect("/");
  }
  const [t, tTenant, state] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    backendFetchWithSession<ActivityPage>("/api/activity"),
  ]);
  const content = state ? <ActivityLog initialPage={state} /> : null;

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
              <RouteTabs tabs={tenantSettingsTabs(t)} activeHref="/tenant-settings/activity" variant="pill" />
              {content}
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
