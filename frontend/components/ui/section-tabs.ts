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
    { href: "/task-packages", label: t("taskPackages") },
  ];
}

// Document Studio: Vorlagen, Corporate Design, Assets, Komponenten, Exporte. Die
// Echtheitsprüfung liegt in den Mandanten-Einstellungen.
export function documentStudioTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/documents", label: t("documentTemplates") },
    { href: "/documents/brand", label: t("documentBrand") },
    { href: "/documents/assets", label: t("documentAssets") },
    { href: "/documents/components", label: t("documentComponents") },
    { href: "/documents/exports", label: t("documentExports") },
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
