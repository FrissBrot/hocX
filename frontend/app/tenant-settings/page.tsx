import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { MobileTenantGeneral } from "@/components/mobile/areas/mobile-tenant";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";

import { EventFieldSettings } from "@/components/settings/event-field-settings";
import { FinanceCurrencySettings } from "@/components/settings/finance-currency-settings";
import { TenantGeneralSettings } from "@/components/settings/tenant-general-settings";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession, resolveManageableTenant } from "@/lib/api/server";

// Einstellungen › Organisation › Profil (Design «hocX Einstellungen»): Stammdaten, Finanzen und
// Spezialfelder der Termine als eigene Abschnitte. Unternavigation kommt aus dem Einstellungen-Rahmen.
export default async function TenantSettingsPage({ searchParams }: { searchParams: Promise<{ tenantId?: string }> }) {
  const { tenantId } = await searchParams;
  const session = await requireSession();
  const tenant = await resolveManageableTenant(session, tenantId);
  const [t, tTenant, tSettings] = await Promise.all([getTranslations("nav"), getTranslations("tenantSettings"), getTranslations("settings")]);
  // Spezialfelder gelten für den angemeldeten Mandanten (API ohne Mandanten-Parameter)
  const isCurrentTenant = tenant.id === session.current_tenant?.id;
  const currency = tenant.finance_currency ?? session.current_tenant?.finance_currency ?? "CHF";

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><MobileTenantGeneral initialTenant={tenant} />{isCurrentTenant && <FinanceCurrencySettings initialCurrency={currency} />}{isCurrentTenant && <EventFieldSettings />}</MobileTenantSettings>}
        desktop={
          <div className="tenant-profile-page">
            <div className="page-header">
              <div>
                <h1 className="page-title">{t("organisationProfile")}</h1>
                <p className="muted">{isCurrentTenant ? tSettings("hub.cards.organisationProfile.description") : tTenant("pageDescription", { tenant: tenant.name })}</p>
              </div>
            </div>
            <TenantGeneralSettings initialTenant={tenant} />
            {isCurrentTenant && <FinanceCurrencySettings initialCurrency={currency} />}
            {isCurrentTenant && <EventFieldSettings />}
          </div>
        }
      />
    </AppShell>
  );
}
