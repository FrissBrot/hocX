import { SessionInfo } from "@/types/api";
import { can, featureAccess, rolesLabel } from "@/lib/permissions";
import { NavIconKey } from "@/components/ui/nav-icons";

// labelKey/titleKey sind next-intl-Schluessel im "nav"-Namespace (frontend/messages/<locale>/nav.json),
// keine fertigen Texte - uebersetzt wird erst beim Rendern (app-shell.tsx), weil buildNav selbst
// keine React-Komponente ist und daher keinen useTranslations()-Hook aufrufen kann.
export type NavLink = { href: string; labelKey: string; icon: NavIconKey; match?: string[] };
// `titleKey: null` renders the links flat, without a group heading (used for the Dashboard).
export type NavGroup = { titleKey: string | null; links: NavLink[] };

/** Rollen des angemeldeten Kontos für Kopfzeile/Profil (mehrere möglich), sonst "Status". */
export function formatRoleLabel(session: Pick<SessionInfo, "roles"> | null | undefined, t: (key: string) => string): string {
  return rolesLabel(session?.roles, t) || t("roles.status");
}

export function isNavLinkActive(link: NavLink, pathname: string): boolean {
  return [link.href, ...(link.match ?? [])].some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function buildNav(session: SessionInfo | null): NavGroup[] {
  const editsMeetings = can(session, "meetings.edit");

  // `match` lists the sibling routes that share a section's tab strip (see RouteTabs), so the
  // section stays highlighted while one of its other tabs is open.
  const groups: NavGroup[] = [
    { titleKey: null, links: [{ href: "/", labelKey: "dashboard", icon: "dashboard", match: ["/statistics"] }] },
    {
      titleKey: "groups.work",
      links: [
        { href: "/protocols", labelKey: "protocols", icon: "protocols" },
        // Leseansicht für meetings.read, Bearbeiten nur mit meetings.edit (Seite selbst prüft).
        ...(can(session, "meetings.read") ? [{ href: "/events", labelKey: "events", icon: "events" as const }] : []),
        { href: "/todos", labelKey: "todos", icon: "todos" },
        { href: "/agenda", labelKey: "agenda", icon: "agenda" },
        ...(can(session, "submissions.manage") ? [{ href: "/submission-assignments", labelKey: "submissions", icon: "submissions" as const }] : []),
        ...(can(session, "finances.read") ? [{ href: "/finances", labelKey: "finances", icon: "finances" as const, match: ["/fines"] }] : []),
      ],
    },
  ];

  const masterData: NavLink[] = [
    ...(can(session, "participants.manage") ? [{ href: "/participants", labelKey: "participants", icon: "participants" as const }] : []),
    ...(editsMeetings ? [{ href: "/lists", labelKey: "lists", icon: "lists" as const }] : []),
    ...(can(session, "files.manage")
      ? [
          { href: "/photos", labelKey: "photos", icon: "photos" as const },
          { href: "/files", labelKey: "files", icon: "files" as const },
          { href: "/shared-links", labelKey: "sharedLinks", icon: "share" as const },
        ]
      : []),
  ];
  if (masterData.length > 0) {
    groups.push({ titleKey: "groups.masterData", links: masterData });
  }

  // Konfiguration in drei Bereichen (Bereichs-Tabs siehe section-tabs.ts): Protokollvorlagen mit
  // Bausteinen, Abläufe (Zyklen, Aufgabenpakete) und Gestaltung der PDFs. templates.edit passt
  // Vorlagen und Gestaltung an; Abläufe brauchen templates.manage.
  // Bussen-Konfiguration (Anwesenheit, Tarife, Pendenzen-Regeln): mit finances.read und Feature finance.
  const configuration: NavLink[] = [
    ...(can(session, "templates.edit")
      ? [
          { href: "/templates", labelKey: "protocolTemplates", icon: "templates" as const, match: ["/elements"] },
          ...(can(session, "templates.manage")
            ? [{ href: "/cycles", labelKey: "workflows", icon: "cycles" as const, match: ["/task-packages"] }]
            : []),
          { href: "/documents", labelKey: "design", icon: "documents" as const, match: ["/documents"] },
        ]
      : []),
    ...(can(session, "finances.read") && featureAccess(session, "finance") !== "none"
      ? [{ href: "/fine-settings", labelKey: "fineSettings", icon: "finances" as const }]
      : []),
  ];
  if (configuration.length > 0) {
    groups.push({ titleKey: "groups.configuration", links: configuration });
  }

  const administration: NavLink[] = [
    ...(can(session, "access.manage") ? [{ href: "/users", labelKey: "users", icon: "users" as const }] : []),
    ...(can(session, "settings.manage") ? [{ href: "/tenant-settings", labelKey: "tenantSettings", icon: "tenant" as const }] : []),
    // Wie bisher nur in der Administration sichtbar (Navigation wie vor RBAC: Rolle admin).
    ...(can(session, "templates.manage") ? [{ href: "/tools/import", labelKey: "import", icon: "tools" as const, match: ["/tools"] }] : []),
  ];
  if (administration.length > 0) {
    groups.push({ titleKey: "groups.administration", links: administration });
  }

  return groups;
}
