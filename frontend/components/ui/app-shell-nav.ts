import { SessionInfo } from "@/types/api";
import { NavIconKey } from "@/components/ui/nav-icons";

export type NavLink = { href: string; label: string; icon: NavIconKey };
export type NavGroup = { title: string; links: NavLink[] };

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

export function buildNav(session: SessionInfo | null): NavGroup[] {
  const role = session?.current_role ?? null;
  const isAdmin = role === "admin";
  const isWriter = isAdmin || role === "writer";
  const hasFinance = isWriter || role === "kassier";

  const workspaceLinks: NavLink[] = [
    { href: "/", label: "Dashboard", icon: "dashboard" },
    { href: "/protocols", label: "Protokolle", icon: "protocols" },
    { href: "/todos", label: "Todos", icon: "todos" },
    { href: "/fines", label: "Bussen", icon: "fines" },
    ...(hasFinance ? [{ href: "/finances", label: "Finanzen", icon: "finances" as const }] : []),
    { href: "/statistics", label: "Statistiken", icon: "statistics" },
  ];

  const groups: NavGroup[] = [{ title: "Übersicht", links: workspaceLinks }];

  if (isWriter) {
    groups.push({
      title: "Datensätze",
      links: [
        { href: "/lists", label: "Listen", icon: "lists" },
        { href: "/participants", label: "Teilnehmer", icon: "participants" },
        { href: "/events", label: "Termine", icon: "events" },
        { href: "/submission-assignments", label: "Abgaben", icon: "submissions" },
      ],
    });
  }

  if (isAdmin) {
    groups.push(
      {
        title: "Struktur",
        links: [
          { href: "/templates", label: "Vorlagen", icon: "templates" },
          { href: "/elements", label: "Elemente", icon: "elements" },
          { href: "/cycles", label: "Zyklen", icon: "cycles" },
        ],
      },
      {
        title: "Administration",
        links: [
          { href: "/users", label: "Benutzer", icon: "users" },
          { href: "/settings", label: "Dokument-Vorlagen", icon: "documents" },
          { href: "/tenant-settings", label: "Mandant-Einstellungen", icon: "tenant" },
        ],
      }
    );
  }

  return groups;
}
