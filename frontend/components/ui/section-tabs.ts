import type { RouteTab } from "@/components/ui/route-tabs";

// Tab sets for the sidebar sections that span several routes. Keep the routes in sync with the
// `match` lists in app-shell-nav.ts so the sidebar entry stays highlighted on every tab.
//
// Functions, not plain constants: this module has no React component to call useTranslations()
// in, so each caller passes its own `t` (usually `useTranslations("nav")`) and gets back the
// RouteTab array with already-translated labels.
type TFunc = (key: string) => string;

export function dashboardTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/", label: t("dashboard") },
    { href: "/statistics", label: t("statistics") },
  ];
}

export function financeTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/finances", label: t("financeAccounts") },
    { href: "/fines", label: t("fines") },
  ];
}

// Admin-only section: every route below redirects non-admins on its own.
export function templateTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/templates", label: t("protocolTemplates") },
    { href: "/elements", label: t("elements") },
    { href: "/settings", label: t("documentLayouts") },
  ];
}

// Admin-only section: every route below redirects non-admins on its own.
export function tenantSettingsTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/tenant-settings", label: t("general") },
    { href: "/tenant-settings/domains", label: t("domains") },
    { href: "/tenant-settings/abo", label: t("subscriptionAndUsage") },
  ];
}
