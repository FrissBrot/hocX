import type { RouteTab } from "@/components/ui/route-tabs";

// Tab sets for the sidebar sections that span several routes. Keep the routes in sync with the
// `match` lists in app-shell-nav.ts so the sidebar entry stays highlighted on every tab.
export const DASHBOARD_TABS: RouteTab[] = [
  { href: "/", label: "Dashboard" },
  { href: "/statistics", label: "Statistiken" },
];

export const FINANCE_TABS: RouteTab[] = [
  { href: "/finances", label: "Konten" },
  { href: "/fines", label: "Bussen" },
];

// Admin-only section: every route below redirects non-admins on its own.
export const TEMPLATE_TABS: RouteTab[] = [
  { href: "/templates", label: "Protokoll-Vorlagen" },
  { href: "/elements", label: "Elemente" },
  { href: "/settings", label: "Dokument-Layouts" },
];
