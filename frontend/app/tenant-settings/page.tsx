import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { MobileTenantGeneral } from "@/components/mobile/areas/mobile-tenant";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";

import { EventFieldSettings } from "@/components/settings/event-field-settings";
import { FinanceCurrencySettings } from "@/components/settings/finance-currency-settings";
import { TenantGeneralSettings } from "@/components/settings/tenant-general-settings";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { tenantSettingsTabs } from "@/components/ui/section-tabs";
import { requireSession, resolveManageableTenant } from "@/lib/api/server";

export default async function TenantSettingsPage({ searchParams }: { searchParams: Promise<{ tenantId?: string }> }) {
  const { tenantId } = await searchParams;
  const session = await requireSession();
  const tenant = await resolveManageableTenant(session, tenantId);
  const [t, tTenant] = await Promise.all([getTranslations("nav"), getTranslations("tenantSettings")]);
  // Spezialfelder gelten für den angemeldeten Mandanten (API ohne Mandanten-Parameter)
  const isCurrentTenant = tenant.id === session.current_tenant?.id;
  const currency = tenant.finance_currency ?? session.current_tenant?.finance_currency ?? "CHF";

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><MobileTenantGeneral initialTenant={tenant} />{isCurrentTenant && <FinanceCurrencySettings initialCurrency={currency} />}{isCurrentTenant && <EventFieldSettings />}</MobileTenantSettings>}
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
              <RouteTabs tabs={tenantSettingsTabs(t)} activeHref="/tenant-settings" variant="pill" />
              <TenantGeneralSettings initialTenant={tenant} />
              {isCurrentTenant && <FinanceCurrencySettings initialCurrency={currency} />}
              {isCurrentTenant && <EventFieldSettings />}
            </div>
          </section>
          </>
        }
      />
    </AppShell>
  );
}
