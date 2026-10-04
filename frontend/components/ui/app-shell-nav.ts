import { SessionInfo } from "@/types/api";
import { NavIconKey } from "@/components/ui/nav-icons";

// labelKey/titleKey sind next-intl-Schluessel im "nav"-Namespace (frontend/messages/<locale>/nav.json),
// keine fertigen Texte - uebersetzt wird erst beim Rendern (app-shell.tsx), weil buildNav selbst
// keine React-Komponente ist und daher keinen useTranslations()-Hook aufrufen kann.
export type NavLink = { href: string; labelKey: string; icon: NavIconKey; match?: string[] };
// `titleKey: null` renders the links flat, without a group heading (used for the Dashboard).
export type NavGroup = { titleKey: string | null; links: NavLink[] };

export function formatRoleLabel(role: string | null | undefined, t: (key: string) => string): string {
  switch (role) {
    case "admin":
      return t("roles.admin");
    case "writer":
      return t("roles.writer");
    case "kassier":
      return t("roles.kassier");
    case "reader":
      return t("roles.reader");
    default:
      return role ?? t("roles.status");
  }
}

export function isNavLinkActive(link: NavLink, pathname: string): boolean {
  return [link.href, ...(link.match ?? [])].some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function buildNav(session: SessionInfo | null): NavGroup[] {
  const role = session?.current_role ?? null;
  const isAdmin = role === "admin";
  const isWriter = isAdmin || role === "writer";
  const hasFinance = role !== null && (session?.current_tenant?.enabled_features?.includes("finance") ?? false);
  const hasAbgabebox = role !== null && (session?.current_tenant?.enabled_features?.includes("abgabebox") ?? false);

  // `match` lists the sibling routes that share a section's tab strip (see RouteTabs), so the
  // section stays highlighted while one of its other tabs is open.
  const groups: NavGroup[] = [
    { titleKey: null, links: [{ href: "/", labelKey: "dashboard", icon: "dashboard", match: ["/statistics"] }] },
    {
      titleKey: "groups.work",
      links: [
        { href: "/protocols", labelKey: "protocols", icon: "protocols" },
        ...(isWriter ? [{ href: "/events", labelKey: "events", icon: "events" as const }] : []),
        { href: "/todos", labelKey: "todos", icon: "todos" },
        ...(isWriter && hasAbgabebox ? [{ href: "/submission-assignments", labelKey: "submissions", icon: "submissions" as const }] : []),
        ...(hasFinance ? [{ href: "/finances", labelKey: "finances", icon: "finances" as const, match: ["/fines"] }] : []),
      ],
    },
  ];

  if (isWriter) {
    groups.push({
      titleKey: "groups.masterData",
      links: [
        { href: "/participants", labelKey: "participants", icon: "participants" },
        { href: "/lists", labelKey: "lists", icon: "lists" },
        { href: "/photos", labelKey: "photos", icon: "photos" },
        { href: "/files", labelKey: "files", icon: "files" },
        { href: "/shared-links", labelKey: "sharedLinks", icon: "share" },
      ],
    });
  }

  if (isAdmin) {
    groups.push(
      {
        titleKey: "groups.configuration",
        links: [
          { href: "/templates", labelKey: "templates", icon: "templates", match: ["/elements", "/settings"] },
          { href: "/cycles", labelKey: "cycles", icon: "cycles" },
        ],
      },
      {
        titleKey: "groups.administration",
        links: [
          { href: "/users", labelKey: "users", icon: "users" },
          { href: "/tenant-settings", labelKey: "tenantSettings", icon: "tenant" },
          { href: "/tools/import", labelKey: "import", icon: "tools", match: ["/tools"] },
        ],
      }
    );
  }

  return groups;
}
