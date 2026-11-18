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
// `titleKey: null` renders the links flat, without a group heading (Start).
// `settings`: die Einstellung, die zu diesem Arbeitsbereich gehört. Sie steht gesammelt in der
// Gruppe «Einstellungen»; die Kopfzeile verlinkt von den Seiten des Bereichs mit einem Zahnrad
// dorthin und von der Einstellung zurück (relatedNavLink).
export type NavGroup = { titleKey: string | null; links: NavLink[]; settings?: NavLink };

export const SETTINGS_GROUP = "groups.settings";

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

/**
 * Seitenleiste nach Tätigkeiten statt nach Technik (Variante C, 2026-11): Start, Sitzungen,
 * Aufgaben, Mitglieder, Kasse, Ablage, Auftritt; darunter alle Einstellungen der Bereiche
 * gesammelt und «Organisation» für das, was den ganzen Mandanten betrifft. Die Adressen der Seiten
 * sind dieselben wie vorher; geändert hat sich nur die Einteilung. Rechte wie bisher.
 */
// Nur Rechte und Module: dieselbe Funktion berechnet auch die Vorschau «Ansehen als …» (Phase 7,
// components/users/access-preview-modal.tsx) - eine Quelle für die echte und die gezeigte Navigation.
// shared_submission_photos (Phase 5) optional: die Vorschau «Ansehen als» (Phase 7) kennt es nicht
export type NavSession = Pick<SessionInfo, "permissions" | "current_tenant"> & Partial<Pick<SessionInfo, "shared_submission_photos">>;

export function buildNav(session: NavSession | null): NavGroup[] {
  const editsMeetings = can(session, "meetings.edit");
  const editsTemplates = can(session, "templates.edit");
  const managesTemplates = can(session, "templates.manage");
  const managesSettings = can(session, "settings.manage");
  const readsFinances = can(session, "finances.read");

  // `match` lists the sibling routes that share a section's tab strip (see RouteTabs), so the
  // section stays highlighted while one of its other tabs is open.
  const areas: NavGroup[] = [
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
        // Leseansicht für meetings.read, Bearbeiten nur mit meetings.edit (Seite selbst prüft).
        ...(can(session, "meetings.read") ? [{ href: "/events", labelKey: "calendar", icon: "events" as const }] : []),
        { href: "/agenda", labelKey: "agenda", icon: "agenda" },
        { href: "/protocols", labelKey: "protocols", icon: "protocols" },
      ],
      // Protokollvorlagen mit Bausteinen; das Arbeitsjahr (Zyklen) braucht templates.manage.
      settings: editsTemplates
        ? { href: "/templates", labelKey: "sessionTemplates", icon: "templates", match: ["/elements", "/cycles"] }
        : undefined,
    },
    {
      titleKey: "groups.tasks",
      links: [
        { href: "/todos", labelKey: "todos", icon: "todos" },
        // Lesezugang für Prüfer und Leser (Phase 4); die Liste filtert das Backend nach Reichweite
        ...(can(session, "submissions.read") ? [{ href: "/submission-assignments", labelKey: "submissions", icon: "submissions" as const }] : []),
      ],
      settings: managesTemplates ? { href: "/task-packages", labelKey: "taskPackages", icon: "cycles" } : undefined,
    },
    {
      titleKey: "groups.members",
      links: can(session, "participants.read") ? [{ href: "/participants", labelKey: "memberList", icon: "participants" }] : [],
      settings: can(session, "access.manage") ? { href: "/users", labelKey: "users", icon: "users" } : undefined,
    },
    {
      titleKey: "groups.cash",
      links: readsFinances
        ? [
            { href: "/finances", labelKey: "financeAccounts", icon: "finances" },
            { href: "/fines", labelKey: "fines", icon: "fines" },
          ]
        : [],
      // Tarife, Anwesenheit, Pendenzen-Regeln: mit finances.read und Feature finance.
      settings: readsFinances && featureAccess(session, "finance") !== "none"
        ? { href: "/fine-settings", labelKey: "fineSettings", icon: "finances" }
        : undefined,
    },
    {
      titleKey: "groups.storage",
      links: [
        ...(editsMeetings ? [{ href: "/lists", labelKey: "lists", icon: "lists" as const }] : []),
        // Getrennte Rechte (Plan «Berechtigungen», Phase 3): Ablage, Fotos, öffentlich teilen
        ...(can(session, "files.read") ? [{ href: "/files", labelKey: "files", icon: "files" as const }] : []),
        ...(can(session, "photos.read") ? [{ href: "/photos", labelKey: "photos", icon: "photos" as const, exclude: ["/photos/submissions"] }] : []),
        // Kontext-Freigaben (Phase 5): Fotos aus Abgaben für Konten ohne «Fotos ansehen»
        ...(session?.shared_submission_photos && !can(session, "photos.read") && can(session, "meetings.read")
          ? [{ href: "/photos/submissions", labelKey: "submissionPhotos", icon: "photos" as const }]
          : []),
        ...(can(session, "sharing.public") ? [{ href: "/shared-links", labelKey: "sharedLinks", icon: "share" as const }] : []),
      ],
    },
    {
      titleKey: "groups.appearance",
      links: editsTemplates
        ? [
            { href: "/documents", labelKey: "documentTemplates", icon: "documents", exclude: ["/documents/brand", "/documents/assets"] },
            { href: "/documents/brand", labelKey: "documentBrand", icon: "studio", match: ["/documents/assets"] },
          ]
        : [],
      settings: managesSettings
        ? { href: "/tenant-settings/domains", labelKey: "domainsAndVerification", icon: "tenant", match: ["/tenant-settings/verification"] }
        : undefined,
    },
  ];

  const groups: NavGroup[] = areas.filter((group) => group.links.length > 0 || group.settings);

  const settingsLinks = areas.flatMap((group) => (group.settings ? [group.settings] : []));
  if (settingsLinks.length > 0) {
    groups.push({ titleKey: SETTINGS_GROUP, links: settingsLinks });
  }

  const organisation: NavLink[] = [
    ...(managesSettings
      ? [
          { href: "/tenant-settings", labelKey: "organisationProfile", icon: "tenant" as const, exact: true },
          { href: "/tenant-settings/abo", labelKey: "subscriptionAndUsage", icon: "storage" as const },
          { href: "/tenant-settings/privacy", labelKey: "privacy", icon: "activity" as const, match: ["/tenant-settings/retention"] },
          { href: "/tenant-settings/links", labelKey: "publicLinks", icon: "share" as const },
        ]
      : []),
    // Aktivitätsprotokoll ist ein eigenes Recht (activity.read, Plan «Berechtigungen» Phase 3)
    ...(can(session, "activity.read") ? [{ href: "/tenant-settings/activity", labelKey: "activity", icon: "activity" as const }] : []),
    // Wie bisher nur in der Administration sichtbar (Navigation wie vor RBAC: Rolle admin).
    ...(managesTemplates ? [{ href: "/tools/import", labelKey: "import", icon: "tools" as const, match: ["/tools"] }] : []),
  ];
  if (organisation.length > 0) {
    groups.push({ titleKey: "groups.organisation", links: organisation });
  }

  // Bereiche, die nur aus ihrer Einstellung bestehen (z. B. Logins ohne Mitgliederliste), stehen
  // nicht als leere Gruppe in der Leiste; ihre Einstellung bleibt unter «Einstellungen».
  return groups.filter((group) => group.links.length > 0);
}

export type RelatedNavLink =
  | { kind: "settings"; link: NavLink }
  | { kind: "area"; groupTitleKey: string; link: NavLink };

/**
 * Querverweis für die Kopfzeile: auf einer Seite eines Arbeitsbereichs dessen Einstellung (Zahnrad),
 * auf einer Einstellung der Bereich, zu dem sie gehört. Nur, was die Person auch öffnen darf
 * (buildNav filtert nach Rechten).
 */
export function relatedNavLink(groups: NavGroup[], pathname: string): RelatedNavLink | null {
  for (const group of groups) {
    if (!group.titleKey || group.titleKey === SETTINGS_GROUP) {
      continue;
    }
    if (group.settings && isNavLinkActive(group.settings, pathname) && group.links[0]) {
      return { kind: "area", groupTitleKey: group.titleKey, link: group.links[0] };
    }
    if (group.settings && group.links.some((link) => isNavLinkActive(link, pathname))) {
      return { kind: "settings", link: group.settings };
    }
  }
  return null;
}
