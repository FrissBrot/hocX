import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { MobileTenantSubscription } from "@/components/mobile/areas/mobile-tenant";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";

import { TenantSubscriptionView } from "@/components/settings/tenant-subscription-view";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession, resolveManageableTenant } from "@/lib/api/server";

export default async function TenantSubscriptionPage({ searchParams }: { searchParams: Promise<{ tenantId?: string }> }) {
  const { tenantId } = await searchParams;
  const session = await requireSession();
  const tenant = await resolveManageableTenant(session, tenantId);
  const [t, tTenant, tSettings] = await Promise.all([getTranslations("nav"), getTranslations("tenantSettings"), getTranslations("settings")]);

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><MobileTenantSubscription initialTenant={tenant} /></MobileTenantSettings>}
        desktop={
          <>
          <section className="panel">
            <div className="section-stack">
              <div className="page-header">
                <div>
                  <h1 className="page-title">{t("subscriptionAndUsage")}</h1>
                  <p className="muted">{tSettings("hub.cards.subscriptionAndUsage.description")}</p>
                </div>
              </div>
              <TenantSubscriptionView initialTenant={tenant} />
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
