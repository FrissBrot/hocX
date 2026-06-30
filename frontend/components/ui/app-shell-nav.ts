import { SessionInfo } from "@/types/api";

export type NavLink = { href: string; label: string };
export type NavGroup = { title: string; links: NavLink[] };

export function formatRoleLabel(role: string | null | undefined): string {
  switch (role) {
    case "superadmin":
      return "Superadmin";
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
  const role = session?.user?.is_superadmin ? "superadmin" : (session?.current_role ?? null);
  const isAdmin = role === "superadmin" || role === "admin";
  const isWriter = isAdmin || role === "writer";
  const hasFinance = isWriter || role === "kassier";

  const workspaceLinks: NavLink[] = [
    { href: "/", label: "Dashboard" },
    { href: "/protocols", label: "Protokolle" },
    { href: "/todos", label: "Todos" },
    { href: "/fines", label: "Bussen" },
    ...(hasFinance ? [{ href: "/finances", label: "Finanzen" }] : []),
  ];

  const groups: NavGroup[] = [{ title: "Workspace", links: workspaceLinks }];

  if (isWriter) {
    groups.push({
      title: "Datensätze",
      links: [
        { href: "/lists", label: "Listen" },
        { href: "/participants", label: "Teilnehmer" },
        { href: "/events", label: "Termine" },
      ],
    });
  }

  if (isAdmin) {
    groups.push(
      {
        title: "Struktur",
        links: [
          { href: "/templates", label: "Templates" },
          { href: "/elements", label: "Elements" },
        ],
      },
      {
        title: "Administration",
        links: [
          { href: "/users", label: "Users" },
          { href: "/tenants", label: "Tenants" },
          { href: "/settings", label: "Document Templates" },
        ],
      }
    );
  }

  return groups;
}
