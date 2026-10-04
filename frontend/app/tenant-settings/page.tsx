import { getTranslations } from "next-intl/server";

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

  return (
    <AppShell initialSession={session}>
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
        </div>
      </section>
    </AppShell>
  );
}
