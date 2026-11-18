import { buildNav } from "@/components/ui/app-shell-nav";
import type { NavIconKey } from "@/components/ui/nav-icons";
import {
  dashboardTabs,
  designAreaTabs,
  domainTabs,
  financeTabs,
  protocolTemplateTabs,
  tenantSettingsTabs,
  userAreaTabs,
} from "@/components/ui/section-tabs";
import { SETTINGS_GROUP } from "@/components/ui/app-shell-nav";
import { can } from "@/lib/permissions";
import type { RouteTab } from "@/components/ui/route-tabs";
import { CONNECTIONS_HREF } from "@/lib/calendar-feeds";
import type { SessionInfo } from "@/types/api";

export type SearchGroup = "recent" | "list" | "pages" | "settings" | "people" | "files";

export type SearchEntry = {
  id: string;
  group: SearchGroup;
  label: string;
  sublabel?: string;
  keywords?: string;
  icon?: NavIconKey;
  href?: string;
  /** Aktion statt Link (Profil, Darstellung) */
  action?: "profile" | "theme-light" | "theme-dark" | "theme-auto" | "list";
};

type TFunc = (key: string) => string;
type HasT = TFunc & { has?: (key: string) => boolean };

// Bereiche mit Unterseiten (section-tabs.ts): Tabs erscheinen als eigene Treffer unter ihrem
// Navigationseintrag - nur wenn der Eintrag selbst sichtbar ist (Rechte prüft buildNav).
const TABS_BY_HREF: Record<string, (t: TFunc, session: SessionInfo | null) => RouteTab[]> = {
  "/": dashboardTabs,
  "/finances": financeTabs,
  // Arbeitsjahr (Zyklen) nur mit templates.manage - wie der Tab auf der Seite selbst.
  "/templates": (t, session) => protocolTemplateTabs(t, can(session, "templates.manage")),
  "/documents/brand": designAreaTabs,
  "/users": userAreaTabs,
  "/tenant-settings": tenantSettingsTabs,
  "/tenant-settings/domains": domainTabs,
};

const SETTINGS_GROUPS = new Set([SETTINGS_GROUP, "groups.organisation"]);

function keywordsFor(tSearch: HasT, key: string): string | undefined {
  const full = `keywords.${key}`;
  return tSearch.has?.(full) ? tSearch(full) : undefined;
}

/**
 * Menüs und Einstellungen, die die Person sehen darf - aus derselben Navigation wie die
 * Seitenleiste (buildNav), damit Suche und Menü nie auseinanderlaufen.
 */
export function buildStaticEntries(session: SessionInfo | null, tNav: TFunc, tSearch: HasT): SearchEntry[] {
  const entries: SearchEntry[] = [];
  const seen = new Set<string>();
  for (const group of buildNav(session)) {
    const groupLabel = group.titleKey ? tNav(group.titleKey) : undefined;
    const kind: SearchGroup = group.titleKey && SETTINGS_GROUPS.has(group.titleKey) ? "settings" : "pages";
    for (const link of group.links) {
      const label = tNav(link.labelKey);
      const tabs = TABS_BY_HREF[link.href]?.(tNav, session) ?? [];
      if (!seen.has(link.href)) {
        seen.add(link.href);
        entries.push({
          id: `nav:${link.href}`,
          group: kind,
          label,
          sublabel: groupLabel,
          keywords: [keywordsFor(tSearch, link.labelKey), ...tabs.filter((tab) => tab.href === link.href).map((tab) => tab.label)].filter(Boolean).join(" "),
          icon: link.icon,
          href: link.href,
        });
      }
      for (const tab of tabs) {
        if (seen.has(tab.href)) continue;
        seen.add(tab.href);
        const tabKey = tab.href.split("/").filter(Boolean).join("-") || "home";
        entries.push({
          id: `nav:${tab.href}`,
          group: kind,
          label: tab.label,
          sublabel: label,
          keywords: keywordsFor(tSearch, tabKey),
          icon: link.icon,
          href: tab.href,
        });
      }
    }
  }

  const account = tNav("profileEdit");
  entries.push(
    { id: "action:profile", group: "settings", label: account, keywords: keywordsFor(tSearch, "profile"), action: "profile" },
    { id: `nav:${CONNECTIONS_HREF}`, group: "settings", label: tNav("connections"), keywords: keywordsFor(tSearch, "connections"), href: CONNECTIONS_HREF },
    { id: "action:theme-light", group: "settings", label: tNav("themeLight"), sublabel: tNav("appearance"), keywords: keywordsFor(tSearch, "theme"), action: "theme-light" },
    { id: "action:theme-dark", group: "settings", label: tNav("themeDark"), sublabel: tNav("appearance"), keywords: keywordsFor(tSearch, "theme"), action: "theme-dark" },
    { id: "action:theme-auto", group: "settings", label: tNav("themeAuto"), sublabel: tNav("appearance"), keywords: keywordsFor(tSearch, "theme"), action: "theme-auto" },
  );
  return entries;
}
