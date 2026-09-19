import { SessionInfo } from "@/types/api";
import { NavIconKey } from "@/components/ui/nav-icons";

export type NavLink = { href: string; label: string; icon: NavIconKey; match?: string[] };
// `title: null` renders the links flat, without a group heading (used for the Dashboard).
export type NavGroup = { title: string | null; links: NavLink[] };

export function formatRoleLabel(role: string | null | undefined): string {
  switch (role) {
    case "admin":
      return "Admin";
    case "writer":
      return "Schreiber";
    case "kassier":
      return "Kassier";
    case "reader":
      return "Leser";
    default:
      return role ?? "Status";
  }
}

export function isNavLinkActive(link: NavLink, pathname: string): boolean {
  return [link.href, ...(link.match ?? [])].some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function buildNav(session: SessionInfo | null): NavGroup[] {
  const role = session?.current_role ?? null;
  const isAdmin = role === "admin";
  const isWriter = isAdmin || role === "writer";
  const hasFinance = role !== null;

  // `match` lists the sibling routes that share a section's tab strip (see RouteTabs), so the
  // section stays highlighted while one of its other tabs is open.
  const groups: NavGroup[] = [
    { title: null, links: [{ href: "/", label: "Dashboard", icon: "dashboard", match: ["/statistics"] }] },
    {
      title: "Arbeiten",
      links: [
        { href: "/protocols", label: "Protokolle", icon: "protocols" },
        ...(isWriter ? [{ href: "/events", label: "Termine", icon: "events" as const }] : []),
        { href: "/todos", label: "Todos", icon: "todos" },
        ...(isWriter ? [{ href: "/submission-assignments", label: "Abgaben", icon: "submissions" as const }] : []),
        ...(hasFinance ? [{ href: "/finances", label: "Finanzen", icon: "finances" as const, match: ["/fines"] }] : []),
      ],
    },
  ];

  if (isWriter) {
    groups.push({
      title: "Stammdaten",
      links: [
        { href: "/participants", label: "Teilnehmer", icon: "participants" },
        { href: "/lists", label: "Stammlisten", icon: "lists" },
        { href: "/photos", label: "Fotos", icon: "photos" },
        { href: "/files", label: "Dateien", icon: "files" },
      ],
    });
  }

  if (isAdmin) {
    groups.push(
      {
        title: "Konfiguration",
        links: [
          { href: "/templates", label: "Vorlagen", icon: "templates", match: ["/elements", "/settings"] },
          { href: "/cycles", label: "Zyklen", icon: "cycles" },
        ],
      },
      {
        title: "Administration",
        links: [
          { href: "/users", label: "Benutzer", icon: "users" },
          { href: "/tenant-settings", label: "Mandant-Einstellungen", icon: "tenant" },
          { href: "/storage", label: "Speicher", icon: "storage" },
          { href: "/tools/import", label: "Import", icon: "tools", match: ["/tools"] },
        ],
      }
    );
  }

  return groups;
}
