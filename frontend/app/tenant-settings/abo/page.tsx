import { TenantSubscriptionView } from "@/components/settings/tenant-subscription-view";
import { AppShell } from "@/components/ui/app-shell";
import { RouteTabs } from "@/components/ui/route-tabs";
import { TENANT_SETTINGS_TABS } from "@/components/ui/section-tabs";
import { requireSession, resolveManageableTenant } from "@/lib/api/server";

export default async function TenantSubscriptionPage({ searchParams }: { searchParams: Promise<{ tenantId?: string }> }) {
  const { tenantId } = await searchParams;
  const session = await requireSession();
  const tenant = await resolveManageableTenant(session, tenantId);

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <div className="section-stack">
          <div className="page-header">
            <div>
              <h1 className="page-title">Mandant-Einstellungen</h1>
              <p className="muted">Stammdaten, Domains und Abo für {tenant.name}.</p>
            </div>
          </div>
          <RouteTabs tabs={TENANT_SETTINGS_TABS} activeHref="/tenant-settings/abo" variant="pill" />
          <TenantSubscriptionView initialTenant={tenant} />
        </div>
      </section>
    </AppShell>
  );
}
