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

// Konfiguration ist in drei Bereiche geteilt, je mit eigenem Eintrag in der Seitenleiste
// (app-shell-nav.ts): was in einer Sitzung vorkommt, wie Sitzungen ablaufen (nur mit
// templates.manage, die Routen leiten alle anderen selbst um) und wie die PDFs aussehen. Der
// Export-Verlauf ist kein Tab, sondern über die Dokumentvorlagen erreichbar.
export function protocolTemplateTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/templates", label: t("templates") },
    { href: "/elements", label: t("elements") },
  ];
}

export function workflowTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/cycles", label: t("cycles") },
    { href: "/task-packages", label: t("taskPackages") },
  ];
}

export function designAreaTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/documents", label: t("documentTemplates") },
    { href: "/documents/brand", label: t("documentBrand") },
    { href: "/documents/assets", label: t("documentAssets") },
  ];
}

// Benutzerverwaltung (access.manage): Konten und Rollen - beide Routen leiten ohne die
// Berechtigung selbst um.
export function userAreaTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/users", label: t("users") },
    { href: "/users/roles", label: t("roleManagement") },
  ];
}

// Admin-only section: every route below redirects non-admins on its own.
export function tenantSettingsTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/tenant-settings", label: t("general") },
    { href: "/tenant-settings/domains", label: t("domains") },
    { href: "/tenant-settings/abo", label: t("subscriptionAndUsage") },
    { href: "/tenant-settings/verification", label: t("documentVerification") },
    { href: "/tenant-settings/privacy", label: t("privacy") },
    { href: "/tenant-settings/retention", label: t("retention") },
    { href: "/tenant-settings/activity", label: t("activity") },
  ];
}
