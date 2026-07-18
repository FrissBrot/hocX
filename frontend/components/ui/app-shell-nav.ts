import { SessionInfo } from "@/types/api";

export type NavLink = { href: string; label: string };
export type NavGroup = { title: string; links: NavLink[] };

export function formatRoleLabel(role: string | null | undefined): string {
  switch (role) {
    case "admin":
      return "Admin";
    case "writer":
      return "Writer";
    case "kassier":
      return "Kassier";
    case "reader":
      return "Reader";
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
    { href: "/", label: "Dashboard" },
    { href: "/protocols", label: "Protokolle" },
    { href: "/todos", label: "Todos" },
    { href: "/fines", label: "Bussen" },
    ...(hasFinance ? [{ href: "/finances", label: "Finanzen" }] : []),
    { href: "/statistics", label: "Statistiken" },
  ];

  const groups: NavGroup[] = [{ title: "Übersicht", links: workspaceLinks }];

  if (isWriter) {
    groups.push({
      title: "Datensätze",
      links: [
        { href: "/lists", label: "Listen" },
        { href: "/participants", label: "Teilnehmer" },
        { href: "/events", label: "Termine" },
        { href: "/submission-assignments", label: "Abgaben" },
      ],
    });
  }

  if (isAdmin) {
    groups.push(
      {
        title: "Struktur",
        links: [
          { href: "/templates", label: "Vorlagen" },
          { href: "/elements", label: "Elemente" },
          { href: "/cycles", label: "Zyklen" },
        ],
      },
      {
        title: "Administration",
        links: [
          { href: "/users", label: "Benutzer" },
          { href: "/settings", label: "Dokument-Vorlagen" },
        ],
      }
    );
  }

  return groups;
}
