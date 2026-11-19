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

/** Bussen aller Arten (Anwesenheit, Pendenzen) stehen in einer Liste unter /fines; ihre
 * Einstellungen unter Konfiguration > Bussen-Konfiguration (/fine-settings). */
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
/** Sitzungsvorlagen: Protokollvorlagen, Bausteine und das Arbeitsjahr (Zyklen, nur mit
 * templates.manage - die Seite prüft es selbst, der Tab erscheint nur, wenn er sich öffnen lässt). */
export function protocolTemplateTabs(t: TFunc, includeWorkYear = false): RouteTab[] {
  return [
    { href: "/templates", label: t("templates") },
    { href: "/elements", label: t("elements") },
    ...(includeWorkYear ? [{ href: "/cycles", label: t("workYear") }] : []),
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
    // «Zugriff» (Konzept «Personen an einem Ort»): Logins und Rollen einer Person ändert man auf
    // ihrer Personenseite; hier stehen Rollen, die Übersicht und die Sicherheitsregeln.
    { href: "/users/roles", label: t("roleManagement") },
    { href: "/users", label: t("accessWho") },
    { href: "/users/security", label: t("accessSecurity") },
  ];
}

/** Früher die Reiter der Organisation; seit dem Einstellungen-Rahmen (Design «hocX Einstellungen»)
 * führt die Unternavigation links dorthin. Bleibt leer bestehen, damit Seiten, die die Reiter noch
 * einbinden (RouteTabs zeigt unter zwei Reitern nichts), ohne Änderung weiter funktionieren. */
export function tenantSettingsTabs(_t: TFunc): RouteTab[] {
  return [];
}

/** Datenschutz: Einstellungen und Aufbewahrungsregeln (beide nur mit settings.manage). */
export function privacyTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/tenant-settings/privacy", label: t("privacy") },
    { href: "/tenant-settings/retention", label: t("retention") },
  ];
}

export function domainTabs(t: TFunc): RouteTab[] {
  return [
    { href: "/tenant-settings/domains", label: t("domains") },
    { href: "/tenant-settings/verification", label: t("documentVerification") },
  ];
}
