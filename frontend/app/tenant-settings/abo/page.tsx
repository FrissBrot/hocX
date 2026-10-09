import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";

import { TenantSubscriptionView } from "@/components/settings/tenant-subscription-view";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { tenantSettingsTabs } from "@/components/ui/section-tabs";
import { requireSession, resolveManageableTenant } from "@/lib/api/server";

export default async function TenantSubscriptionPage({ searchParams }: { searchParams: Promise<{ tenantId?: string }> }) {
  const { tenantId } = await searchParams;
  const session = await requireSession();
  const tenant = await resolveManageableTenant(session, tenantId);
  const [t, tTenant] = await Promise.all([getTranslations("nav"), getTranslations("tenantSettings")]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><TenantSubscriptionView initialTenant={tenant} /></MobileTenantSettings>}
        desktop={
          <>
          <section className="panel">
            <div className="section-stack">
              <div className="page-header">
                <div>
                  <h1 className="page-title">{tTenant("pageTitle")}</h1>
                  <p className="muted">{tTenant("pageDescription", { tenant: tenant.name })}</p>
                </div>
              </div>
              <RouteTabs tabs={tenantSettingsTabs(t)} activeHref="/tenant-settings/abo" variant="pill" />
              <TenantSubscriptionView initialTenant={tenant} />
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
