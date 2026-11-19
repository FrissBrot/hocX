import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { ResponsiveView } from "@/components/mobile/responsive-view";
import {
  SettingsOverview,
  type SettingsAttentionItem,
  type SettingsCardStatus,
} from "@/components/settings/settings-overview";
import { AppShell } from "@/components/ui/app-shell";
import { buildSettingsNav } from "@/components/ui/app-shell-nav";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";
import type { PublicLinkItem } from "@/types/api";

// Übersicht aller Einstellungen (Design «hocX Einstellungen»). Früher leitete /settings auf das
// Erscheinungsbild weiter; das steht jetzt als Karte unter «Auftritt».
export default async function SettingsPage() {
  const session = await requireSession();
  const groups = buildSettingsNav(session);
  if (groups.length === 0) {
    redirect("/");
  }
  const managesSettings = can(session, "settings.manage");
  const [t, publicLinks] = await Promise.all([
    getTranslations("settings.hub"),
    // Zugangslinks (settings.manage): Statuszeile und «Braucht Aufmerksamkeit» (Links ohne Ablauf)
    managesSettings ? backendFetchWithSession<PublicLinkItem[]>("/api/public-links").catch(() => null) : Promise.resolve(null),
  ]);

  // Statuszeilen nur, wo sie ohne zusätzliche Abfrage aus der Sitzung kommen (bzw. aus den
  // Zugangslinks, die ohnehin für «Braucht Aufmerksamkeit» geladen werden).
  const tenant = session.current_tenant;
  const statuses: Record<string, SettingsCardStatus> = {};
  if (tenant) {
    statuses["/tenant-settings"] = tenant.identity_verified
      ? { text: t("status.verified"), tone: "success" }
      : { text: t("status.currency", { currency: tenant.finance_currency ?? "CHF" }), tone: "neutral" };
    statuses["/tenant-settings/abo"] = { text: t("status.modules", { count: tenant.enabled_features.length }), tone: "neutral" };
    statuses["/users"] = tenant.require_mfa
      ? { text: t("status.mfaRequired"), tone: "success" }
      : { text: t("status.mfaOptional"), tone: "neutral" };
  }

  const attention: SettingsAttentionItem[] = [];
  if (publicLinks) {
    const neverExpiring = publicLinks.filter((link) => link.expiry === "never").length;
    statuses["/tenant-settings/links"] = {
      text: t("status.publicLinks", { count: publicLinks.length }),
      tone: neverExpiring > 0 ? "warning" : "neutral",
    };
    if (neverExpiring > 0) {
      attention.push({
        id: "links-without-expiry",
        title: t("linksWithoutExpiry", { count: neverExpiring }),
        hint: t("linksWithoutExpiryHint"),
        href: "/tenant-settings/links",
      });
    }
  }

  const props = { groups, tenantName: tenant?.name ?? "", statuses, attention };
  return (
    <AppShell initialSession={session}>
      <ResponsiveView mobile={<SettingsOverview {...props} mobile />} desktop={<SettingsOverview {...props} />} />
    </AppShell>
  );
}
