import { buildNav, buildSettingsNav, SETTINGS_GROUP, SETTINGS_HREF, type NavGroup } from "@/components/ui/app-shell-nav";
import type { NavIconKey } from "@/components/ui/nav-icons";
import {
  dashboardTabs,
  designAreaTabs,
  domainTabs,
  financeTabs,
  privacyTabs,
  protocolTemplateTabs,
  userAreaTabs,
} from "@/components/ui/section-tabs";
import { can } from "@/lib/permissions";
import type { RouteTab } from "@/components/ui/route-tabs";
import { CONNECTIONS_HREF } from "@/lib/calendar-feeds";
import type { SessionInfo } from "@/types/api";
import { buildSettingEntries } from "@/lib/search/setting-entries";

export type SearchGroup = "recent" | "list" | "pages" | "settings" | "roles" | "elements" | "people" | "files";

export type SearchEntry = {
  id: string;
  group: SearchGroup;
  label: string;
  sublabel?: string;
  keywords?: string;
  icon?: NavIconKey;
  href?: string;
  /** Aktion statt Link (Profil, Darstellung) */
  action?: "profile" | "theme-light" | "theme-dark" | "theme-auto";
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
  "/tenant-settings/privacy": privacyTabs,
  "/tenant-settings/domains": domainTabs,
};

function keywordsFor(tSearch: HasT, key: string): string | undefined {
  const full = `keywords.${key}`;
  return tSearch.has?.(full) ? tSearch(full) : undefined;
}

/**
 * Menüs und Einstellungen, die die Person sehen darf - aus derselben Navigation wie die
 * Seitenleiste (buildNav) und die Einstellungen-Übersicht (buildSettingsNav), damit Suche und
 * Menü nie auseinanderlaufen.
 */
export function buildStaticEntries(session: SessionInfo | null, tNav: TFunc, tSearch: HasT): SearchEntry[] {
  const entries: SearchEntry[] = [];
  const seen = new Set<string>();
  const settingsGroups = buildSettingsNav(session);
  const sections: { group: NavGroup; kind: SearchGroup }[] = [
    ...buildNav(session).map((group) => ({ group, kind: "pages" as const })),
    ...settingsGroups.map((group) => ({ group, kind: "settings" as const })),
  ];
  // Übersicht aller Einstellungen (Knopf «Einstellungen» in der Seitenleiste)
  if (settingsGroups.length > 0) {
    seen.add(SETTINGS_HREF);
    entries.push({
      id: `nav:${SETTINGS_HREF}`,
      group: "settings",
      label: tNav(SETTINGS_GROUP),
      keywords: keywordsFor(tSearch, "settings"),
      icon: "tenant",
      href: SETTINGS_HREF,
    });
  }
  for (const { group, kind } of sections) {
    const groupLabel = group.titleKey ? tNav(group.titleKey) : undefined;
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
          // Stichwörter über den Schlüssel des Eintrags und über seinen Pfad (früher ein Tab, z. B.
          // tenant-settings-privacy: «DSGVO» findet «Datenschutz» weiterhin)
          keywords: [
            keywordsFor(tSearch, link.labelKey),
            keywordsFor(tSearch, link.href.split("/").filter(Boolean).join("-") || "home"),
            ...tabs.filter((tab) => tab.href === link.href).map((tab) => tab.label),
          ].filter(Boolean).join(" "),
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

  // Einzelne Einstellungen (Abschnitte/Reiter) der sichtbaren Seiten
  const labels = new Map(entries.map((entry) => [entry.href, entry.label]));
  entries.push(...buildSettingEntries(seen, tSearch, (href) => labels.get(href)));

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
