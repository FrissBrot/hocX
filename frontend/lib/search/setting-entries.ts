import type { NavIconKey } from "@/components/ui/nav-icons";
import type { SearchEntry } from "@/lib/search/static-entries";

/**
 * Einzelne Einstellungen für die Suche (Ctrl+K): Abschnitte innerhalb der Einstellungsseiten,
 * mit Sprungmarke (#id auf der Seite, Klasse settings-anchor) bzw. Reiter (?tab=). Ein Eintrag
 * erscheint nur, wenn die Seite selbst in der Navigation sichtbar ist (``page``) - Rechte prüft
 * also weiterhin buildNav. Texte: search.json › settingEntries.<id>.label/keywords.
 * Neue Einstellung mit eigenem Abschnitt: hier eintragen und Übersetzungen ergänzen.
 */
type SettingDef = { id: string; page: string; href: string; icon: NavIconKey };

export const SETTING_DEFS: SettingDef[] = [
  { id: "tenantName", page: "/tenant-settings", href: "/tenant-settings#stammdaten", icon: "tenant" },
  { id: "tenantLogo", page: "/tenant-settings", href: "/tenant-settings#stammdaten", icon: "tenant" },
  { id: "publicSlug", page: "/tenant-settings", href: "/tenant-settings#stammdaten", icon: "tenant" },
  { id: "eventFields", page: "/tenant-settings", href: "/tenant-settings#event-fields", icon: "tenant" },
  { id: "currencies", page: "/tenant-settings", href: "/tenant-settings#currencies", icon: "tenant" },
  { id: "privacyStatistics", page: "/tenant-settings/privacy", href: "/tenant-settings/privacy#privacy-statistics", icon: "tenant" },
  { id: "privacyNotice", page: "/tenant-settings/privacy", href: "/tenant-settings/privacy#privacy-notice", icon: "tenant" },
  { id: "retentionRules", page: "/tenant-settings/retention", href: "/tenant-settings/retention#retention-rules", icon: "tenant" },
  { id: "retentionProposals", page: "/tenant-settings/retention", href: "/tenant-settings/retention#retention-proposals", icon: "tenant" },
  { id: "fineTariff", page: "/fine-settings", href: "/fine-settings?tab=attendance", icon: "finances" },
  { id: "fineTariffGroups", page: "/fine-settings", href: "/fine-settings?tab=tariffs", icon: "finances" },
  { id: "todoFineRules", page: "/fine-settings", href: "/fine-settings?tab=rules", icon: "finances" },
];

type HasT = ((key: string) => string) & { has?: (key: string) => boolean };

export function buildSettingEntries(visiblePages: Set<string>, tSearch: HasT, pageLabel: (href: string) => string | undefined): SearchEntry[] {
  return SETTING_DEFS.filter((def) => visiblePages.has(def.page)).map((def) => {
    const keywords = `settingEntries.${def.id}.keywords`;
    return {
      id: `setting:${def.id}`,
      group: "settings",
      label: tSearch(`settingEntries.${def.id}.label`),
      sublabel: pageLabel(def.page),
      keywords: tSearch.has?.(keywords) ? tSearch(keywords) : undefined,
      icon: def.icon,
      href: def.href,
    };
  });
}
