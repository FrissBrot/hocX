import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { ActivityLog } from "@/components/settings/activity-log";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { ActivityPage } from "@/types/api";
import { can } from "@/lib/permissions";

// Verlauf des aktiven Mandanten (nur Mandanten-Admins, Datenschutz-Audit PRIV-013).
export default async function TenantActivityPage() {
  const session = await requireSession();
  if (!can(session, "activity.read")) {
    redirect("/");
  }
  const [t, tTenant, tSettings, state] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    getTranslations("settings"),
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
                  <h1 className="page-title">{t("activity")}</h1>
                  <p className="muted">{tSettings("hub.cards.activity.description")}</p>
                </div>
              </div>
              {content}
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
