import { MobileTenantSettings } from "@/components/mobile/areas/mobile-admin";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PublicLinksOverview } from "@/components/settings/public-links-overview";
import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import type { PartnerHistoryEntry, PublicLinkItem } from "@/types/api";
import { can } from "@/lib/permissions";

// Zugangslinks: alle gerade gültigen Wege ohne Anmeldung zu Daten des Vereins (app/public_links).
export default async function TenantPublicLinksPage() {
  const session = await requireSession();
  if (!can(session, "settings.manage")) {
    redirect("/");
  }
  const [t, tTenant, tLinks, state, history] = await Promise.all([
    getTranslations("nav"),
    getTranslations("tenantSettings"),
    getTranslations("tenantSettings.publicLinks"),
    backendFetchWithSession<PublicLinkItem[]>("/api/public-links"),
    // Der Partner-Verlauf ist Zusatz: fehlt er, bleibt die Liste trotzdem nutzbar
    backendFetchWithSession<PartnerHistoryEntry[]>("/api/public-links/partner-history").catch(() => null),
  ]);
  const props = {
    links: state ?? [],
    history: history ?? [],
    canRevoke: can(session, "sharing.public"),
    canOpenActivity: can(session, "activity.read"),
  };
  const content = <PublicLinksOverview {...props} />;
  const mobileContent = <PublicLinksOverview {...props} mobile />;

  return (
    <AppShell initialSession={session}>
      <ResponsiveView
        mobile={<MobileTenantSettings title={tTenant("pageTitle")}><div className="mobile-section">{mobileContent}</div></MobileTenantSettings>}
        desktop={
          <>
          <section className="panel">
            <div className="section-stack">
              <div className="page-header">
                <div>
                  <div className="eyebrow">{tLinks("eyebrow")}</div>
                  <h1 className="page-title">{t("publicLinks")}</h1>
                  {/* Ein einziger Lead-Text (früher doppelt: Kopf und Liste) */}
                  <p className="muted public-links-lead">{tLinks("intro")}</p>
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
