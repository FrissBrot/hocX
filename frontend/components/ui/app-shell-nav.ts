import { SessionInfo } from "@/types/api";
import { can, featureAccess, rolesLabel } from "@/lib/permissions";
import { NavIconKey } from "@/components/ui/nav-icons";

// labelKey/titleKey sind next-intl-Schluessel im "nav"-Namespace (frontend/messages/<locale>/nav.json),
// keine fertigen Texte - uebersetzt wird erst beim Rendern (app-shell.tsx), weil buildNav selbst
// keine React-Komponente ist und daher keinen useTranslations()-Hook aufrufen kann.
//
// match:   weitere Routen, die den Eintrag aktiv halten (Geschwister-Tabs, siehe RouteTabs)
// exact:   nur genau diese Route (z. B. /tenant-settings, dessen Unterseiten eigene Einträge sind)
// exclude: Unterrouten, die zu einem anderen Eintrag gehören (z. B. /documents/brand)
export type NavLink = { href: string; labelKey: string; icon: NavIconKey; match?: string[]; exact?: boolean; exclude?: string[] };
// `titleKey: null` renders the links flat, without a group heading (Übersicht, Meine Aufgaben).
export type NavGroup = { titleKey: string | null; links: NavLink[] };

// Einstellung, die zu einem Arbeitsbereich gehört (z. B. Bussen-Regeln zur Kasse): Auf den Seiten
// `hrefs` zeigt die Kopfzeile ein Zahnrad zur Einstellung, auf der Einstellung den Chip «← Zurück
// zu <titleKey>» (relatedNavLink). titleKey ist ein Schlüssel im "nav"-Namespace.
export type SettingsArea = { titleKey: string; hrefs: string[] };
export type SettingsLink = NavLink & { area?: SettingsArea };
export type SettingsGroup = { titleKey: string; links: SettingsLink[] };

/** Beschriftung des Einstellungen-Knopfs und der Kopfzeile (nav.groups.settings). */
export const SETTINGS_GROUP = "groups.settings";

/** Übersicht aller Einstellungen (Knopf unten in der Seitenleiste, Design «hocX Einstellungen»). */
export const SETTINGS_HREF = "/settings";

/** Rollen des angemeldeten Kontos für Kopfzeile/Profil (mehrere möglich), sonst "Status". */
export function formatRoleLabel(session: Pick<SessionInfo, "roles"> | null | undefined, t: (key: string) => string): string {
  return rolesLabel(session?.roles, t) || t("roles.status");
}

function matchesPrefix(prefix: string, pathname: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function isNavLinkActive(link: NavLink, pathname: string): boolean {
  if (link.exclude?.some((prefix) => matchesPrefix(prefix, pathname))) {
    return false;
  }
  if (link.exact) {
    return pathname === link.href || (link.match ?? []).some((prefix) => matchesPrefix(prefix, pathname));
  }
  return [link.href, ...(link.match ?? [])].some((prefix) => matchesPrefix(prefix, pathname));
}

// Nur Rechte und Module: dieselben Funktionen berechnen auch die Vorschau «Ansehen als …» (Phase 7,
// components/users/access-preview-modal.tsx) - eine Quelle für die echte und die gezeigte Navigation.
// shared_submission_photos (Phase 5) optional: die Vorschau «Ansehen als» (Phase 7) kennt es nicht
export type NavSession = Pick<SessionInfo, "permissions" | "current_tenant"> & Partial<Pick<SessionInfo, "shared_submission_photos">>;

/**
 * Seitenleiste nach Tätigkeiten (Design «hocX Einstellungen», 2026-11): Übersicht und Meine
 * Aufgaben ohne Gruppe, dann Sitzungen, Aufgaben, Kasse, Ablage. Einstellungen stehen nicht mehr
 * in der Leiste, sondern hinter dem Knopf «Einstellungen» über der Benutzerkarte (buildSettingsNav,
 * Übersicht /settings). Die Adressen der Seiten sind dieselben wie vorher. Rechte wie bisher.
 */
export function buildNav(session: NavSession | null): NavGroup[] {
  const readsFinances = can(session, "finances.read");

  // `match` lists the sibling routes that share a section's tab strip (see RouteTabs), so the
  // section stays highlighted while one of its other tabs is open.
  const groups: NavGroup[] = [
    {
      titleKey: null,
      links: [
        { href: "/", labelKey: "dashboard", icon: "dashboard", match: ["/statistics"], exact: true },
        { href: "/my-tasks", labelKey: "myTasks", icon: "todos" },
      ],
    },
    {
      titleKey: "groups.sessions",
      links: [
        { href: "/protocols", labelKey: "protocols", icon: "protocols" },
        // Leseansicht für meetings.read, Bearbeiten nur mit meetings.edit (Seite selbst prüft).
        ...(can(session, "meetings.read") ? [{ href: "/events", labelKey: "calendar", icon: "events" as const }] : []),
        { href: "/agenda", labelKey: "agenda", icon: "agenda" },
      ],
    },
    {
      titleKey: "groups.tasks",
      links: [
        { href: "/todos", labelKey: "todos", icon: "todos" },
        // Lesezugang für Prüfer und Leser (Phase 4); die Liste filtert das Backend nach Reichweite
        ...(can(session, "submissions.read") ? [{ href: "/submission-assignments", labelKey: "submissions", icon: "submissions" as const }] : []),
      ],
    },
    {
      titleKey: "groups.cash",
      links: readsFinances
        ? [
            { href: "/finances", labelKey: "financeAccounts", icon: "finances" },
            { href: "/fines", labelKey: "fines", icon: "fines" },
          ]
        : [],
    },
    {
      titleKey: "groups.storage",
      links: [
        ...(can(session, "participants.read") ? [{ href: "/participants", labelKey: "participants", icon: "participants" as const }] : []),
        // Getrennte Rechte (Plan «Berechtigungen», Phase 3): Ablage, Fotos, öffentlich teilen
        ...(can(session, "files.read") ? [{ href: "/files", labelKey: "files", icon: "files" as const }] : []),
        ...(can(session, "photos.read") ? [{ href: "/photos", labelKey: "photos", icon: "photos" as const, exclude: ["/photos/submissions"] }] : []),
        // Kontext-Freigaben (Phase 5): Fotos aus Abgaben für Konten ohne «Fotos ansehen»
        ...(session?.shared_submission_photos && !can(session, "photos.read") && can(session, "meetings.read")
          ? [{ href: "/photos/submissions", labelKey: "submissionPhotos", icon: "photos" as const }]
          : []),
        ...(can(session, "meetings.edit") ? [{ href: "/lists", labelKey: "lists", icon: "lists" as const }] : []),
      ],
    },
  ];

  return groups.filter((group) => group.links.length > 0);
}

/**
 * Alle Einstellungen, die die Person öffnen darf, in den Gruppen der Übersicht (/settings):
 * Bereiche (Einstellungen eines Arbeitsbereichs), Auftritt, Organisation. Eine Quelle für die
 * Übersicht, die Unternavigation im Einstellungen-Rahmen, die globale Suche und «Mehr» (Mobile).
 */
export function buildSettingsNav(session: NavSession | null): SettingsGroup[] {
  const editsTemplates = can(session, "templates.edit");
  const managesTemplates = can(session, "templates.manage");
  const managesSettings = can(session, "settings.manage");

  const groups: SettingsGroup[] = [
    {
      titleKey: "groups.settingsAreas",
      links: [
        // Protokollvorlagen mit Bausteinen; das Arbeitsjahr (Zyklen) braucht templates.manage.
        ...(editsTemplates
          ? [{
              href: "/templates", labelKey: "sessionTemplates", icon: "templates" as const, match: ["/elements", "/cycles"],
              area: { titleKey: "groups.sessions", hrefs: ["/protocols", "/events", "/agenda"] },
            }]
          : []),
        ...(managesTemplates
          ? [{ href: "/task-packages", labelKey: "taskPackages", icon: "cycles" as const, area: { titleKey: "groups.tasks", hrefs: ["/todos", "/submission-assignments"] } }]
          : []),
        // Tarife, Anwesenheit, Pendenzen-Regeln: mit finances.read und Feature finance.
        ...(can(session, "finances.read") && featureAccess(session, "finance") !== "none"
          ? [{ href: "/fine-settings", labelKey: "fineSettings", icon: "fines" as const, area: { titleKey: "groups.cash", hrefs: ["/finances", "/fines"] } }]
          : []),
        ...(can(session, "access.manage")
          ? [{ href: "/users", labelKey: "users", icon: "users" as const, area: { titleKey: "participants", hrefs: ["/participants"] } }]
          : []),
      ],
    },
    {
      titleKey: "groups.appearance",
      links: [
        ...(editsTemplates
          ? [
              { href: "/documents", labelKey: "documentTemplates", icon: "documents" as const, exclude: ["/documents/brand", "/documents/assets"] },
              { href: "/documents/brand", labelKey: "documentBrand", icon: "studio" as const, match: ["/documents/assets"] },
            ]
          : []),
        ...(managesSettings
          ? [{ href: "/tenant-settings/domains", labelKey: "domainsAndVerification", icon: "tenant" as const, match: ["/tenant-settings/verification"] }]
          : []),
      ],
    },
    {
      titleKey: "groups.organisation",
      links: [
        ...(managesSettings
          ? [
              { href: "/tenant-settings", labelKey: "organisationProfile", icon: "tenant" as const, exact: true },
              { href: "/tenant-settings/abo", labelKey: "subscriptionAndUsage", icon: "storage" as const },
              { href: "/tenant-settings/privacy", labelKey: "privacy", icon: "activity" as const, match: ["/tenant-settings/retention"] },
              { href: "/tenant-settings/links", labelKey: "publicLinks", icon: "share" as const },
            ]
          : []),
        ...(can(session, "sharing.public") ? [{ href: "/shared-links", labelKey: "sharedLinks", icon: "share" as const }] : []),
        // Aktivitätsprotokoll ist ein eigenes Recht (activity.read, Plan «Berechtigungen» Phase 3)
        ...(can(session, "activity.read") ? [{ href: "/tenant-settings/activity", labelKey: "activity", icon: "activity" as const }] : []),
        // Sicherheit & Anmeldungen: eigenes Recht security.read (Standardrolle admin, Admin-Redesign Phase E)
        ...(can(session, "security.read") ? [{ href: "/tenant-settings/security", labelKey: "securityLogins", icon: "activity" as const }] : []),
        // Wie bisher nur in der Administration sichtbar (Navigation wie vor RBAC: Rolle admin).
        ...(managesTemplates ? [{ href: "/tools/import", labelKey: "import", icon: "tools" as const, match: ["/tools"] }] : []),
      ],
    },
  ];
  return groups.filter((group) => group.links.length > 0);
}

/** Die Einstellung, zu der `pathname` gehört (oder null). /settings selbst ist die Übersicht. */
export function activeSettingsLink(settings: SettingsGroup[], pathname: string): SettingsLink | null {
  for (const group of settings) {
    const link = group.links.find((candidate) => isNavLinkActive(candidate, pathname));
    if (link) return link;
  }
  return null;
}

/** Übersicht oder eine Einstellungsseite: Knopf «Einstellungen» aktiv, Einstellungen-Rahmen. */
export function isSettingsPath(settings: SettingsGroup[], pathname: string): boolean {
  return pathname === SETTINGS_HREF || activeSettingsLink(settings, pathname) !== null;
}

export type RelatedNavLink =
  | { kind: "settings"; link: NavLink }
  | { kind: "area"; groupTitleKey: string; link: NavLink };

/**
 * Querverweis für die Kopfzeile: auf einer Seite eines Arbeitsbereichs dessen Einstellung (Zahnrad),
 * auf einer Einstellung der Chip «← Zurück zu <Bereich>». Nur, was die Person auch öffnen darf
 * (buildNav/buildSettingsNav filtern nach Rechten).
 */
export function relatedNavLink(groups: NavGroup[], settings: SettingsGroup[], pathname: string): RelatedNavLink | null {
  const areaLinks = groups.flatMap((group) => group.links);
  for (const link of settings.flatMap((group) => group.links)) {
    if (!link.area) continue;
    const targets = link.area.hrefs.flatMap((href) => areaLinks.filter((candidate) => candidate.href === href));
    if (targets.length === 0) continue;
    if (isNavLinkActive(link, pathname)) {
      return { kind: "area", groupTitleKey: link.area.titleKey, link: targets[0] };
    }
    if (targets.some((target) => isNavLinkActive(target, pathname))) {
      return { kind: "settings", link };
    }
  }
  return null;
}
