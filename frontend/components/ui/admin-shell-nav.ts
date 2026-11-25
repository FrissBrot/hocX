// Navigation des Plattform-Admins (Admin-Redesign, Plan §2): sieben Bereiche A–G als reine Daten,
// damit Sidebar, Brotkrumen und die Befehlspalette (Ctrl+K) dieselbe Quelle nutzen und die Logik
// ohne React testbar ist (Muster: app-shell-nav.ts).
//
// labelKey/titleKey sind Schlüssel im Namespace "adminShell" - übersetzt wird erst beim Rendern.
// ownerOnly: Seiten, deren Daten das Backend nur owner-Admins gibt (require_admin_owner, Plan
// «O»); für support blendet die Navigation sie aus, statt eine 403-Seite zu zeigen.

export type AdminRole = "owner" | "support";

export type AdminIconKey =
  | "dashboard" | "tenants" | "pricing" | "cashflow" | "users" | "domains" | "verifications" | "documents"
  | "errors" | "pipeline" | "jobs" | "system" | "notifications" | "admins" | "security" | "storage"
  | "backups" | "maintenance" | "analytics" | "settings" | "delivery" | "blocks" | "events" | "alerts"
  | "policy" | "audit" | "account";

/** Zähler aus GET /api/admin/nav-counts */
export type AdminNavCountKey = "tenants" | "verifications_open" | "security_alerts" | "operations_problems";
/** Status-Punkt eines Eintrags (Backups: läuft/Warnung/kritisch, sonst kein Punkt). */
export type AdminNavStatus = "running" | "warning" | "critical";
export type AdminNavCounts = Record<AdminNavCountKey, number | null> & { backup_status?: AdminNavStatus | null };

export type AdminNavLink = {
  href: string;
  labelKey: string;
  icon: AdminIconKey;
  badge?: AdminNavCountKey;
  /** Status-Punkt aus GET /api/admin/nav-counts (Feld backup_status) */
  status?: "backup_status";
  ownerOnly?: boolean;
  /** zusätzliche Suchbegriffe für Ctrl+K (Schlüssel in adminShell.keywords.*) */
  keywordsKey?: string;
};

export type AdminNavGroup = {
  id: string;
  titleKey: string | null;
  badge?: AdminNavCountKey;
  links: AdminNavLink[];
};

const NAV: AdminNavGroup[] = [
  { id: "overview", titleKey: null, links: [{ href: "/admin", labelKey: "nav.dashboard", icon: "dashboard" }] },
  {
    id: "tenants",
    titleKey: "groups.tenants",
    links: [
      { href: "/admin/tenants", labelKey: "nav.tenants", icon: "tenants", badge: "tenants" },
      { href: "/admin/verifications", labelKey: "nav.verifications", icon: "verifications", badge: "verifications_open" },
      { href: "/admin/domains", labelKey: "nav.domains", icon: "domains" },
      { href: "/admin/plans", labelKey: "nav.pricing", icon: "pricing", keywordsKey: "keywords.pricing" },
      { href: "/admin/cashflow", labelKey: "nav.cashflow", icon: "cashflow", keywordsKey: "keywords.cashflow" },
    ],
  },
  {
    id: "access",
    titleKey: "groups.access",
    links: [
      { href: "/admin/users", labelKey: "nav.users", icon: "users", ownerOnly: true },
      { href: "/admin/admins", labelKey: "nav.admins", icon: "admins", ownerOnly: true },
    ],
  },
  {
    id: "security",
    titleKey: "groups.security",
    badge: "security_alerts",
    links: [
      { href: "/admin/security", labelKey: "nav.securityOverview", icon: "security" },
      { href: "/admin/security/events", labelKey: "nav.securityEvents", icon: "events", ownerOnly: true },
      { href: "/admin/security/blocks", labelKey: "nav.securityBlocks", icon: "blocks", ownerOnly: true },
      { href: "/admin/security/alerts", labelKey: "nav.securityAlerts", icon: "alerts", ownerOnly: true, badge: "security_alerts" },
      { href: "/admin/security/audit", labelKey: "nav.auditLog", icon: "audit", ownerOnly: true },
      { href: "/admin/security/policy", labelKey: "nav.securityPolicy", icon: "policy", ownerOnly: true },
    ],
  },
  {
    id: "operations",
    titleKey: "groups.operations",
    badge: "operations_problems",
    links: [
      { href: "/admin/system", labelKey: "nav.systemStatus", icon: "system", ownerOnly: true, badge: "operations_problems" },
      { href: "/admin/jobs", labelKey: "nav.jobs", icon: "jobs", ownerOnly: true },
      { href: "/admin/error-logs", labelKey: "nav.errorLogs", icon: "errors", ownerOnly: true },
      { href: "/admin/upload-pipeline", labelKey: "nav.uploadPipeline", icon: "pipeline", ownerOnly: true },
      { href: "/admin/cloud-imports", labelKey: "nav.cloudImports", icon: "pipeline", ownerOnly: true, keywordsKey: "keywords.cloudImports" },
      { href: "/admin/operations/delivery", labelKey: "nav.delivery", icon: "delivery", ownerOnly: true },
      { href: "/admin/storage", labelKey: "nav.storage", icon: "storage" },
      { href: "/admin/backups", labelKey: "nav.backups", icon: "backups", status: "backup_status" },
      { href: "/admin/maintenance", labelKey: "nav.maintenance", icon: "maintenance" },
    ],
  },
  {
    id: "analytics",
    titleKey: "groups.analytics",
    links: [{ href: "/admin/analytics", labelKey: "nav.analytics", icon: "analytics" }],
  },
  {
    id: "settings",
    titleKey: "groups.settings",
    links: [
      { href: "/admin/settings/notifications", labelKey: "nav.notifications", icon: "notifications", ownerOnly: true, keywordsKey: "keywords.notifications" },
      { href: "/admin/document-templates", labelKey: "nav.documentTemplates", icon: "documents" },
      // 1.5.1: read-only Einstellungsseiten
      { href: "/admin/settings/security", labelKey: "nav.settingsSecurity", icon: "policy", keywordsKey: "keywords.settingsSecurity" },
      { href: "/admin/settings/integrations", labelKey: "nav.settingsIntegrations", icon: "settings", ownerOnly: true, keywordsKey: "keywords.settingsIntegrations" },
      { href: "/admin/settings/system", labelKey: "nav.settingsSystem", icon: "system", ownerOnly: true, keywordsKey: "keywords.settingsSystem" },
    ],
  },
];

/** Seiten ausserhalb der Sidebar, die trotzdem Brotkrumen und einen Ctrl+K-Eintrag haben. */
export const ADMIN_EXTRA_LINKS: AdminNavLink[] = [
  { href: "/admin/account", labelKey: "nav.account", icon: "account", keywordsKey: "keywords.account" },
];

/** Navigation für eine Rolle: owner-Seiten für support ausgeblendet, leere Gruppen entfallen. */
export function buildAdminNav(role: AdminRole | null | undefined): AdminNavGroup[] {
  const isOwner = role === "owner";
  return NAV.map((group) => ({ ...group, links: group.links.filter((link) => isOwner || !link.ownerOnly) })).filter(
    (group) => group.links.length > 0,
  );
}

function matches(href: string, pathname: string): boolean {
  return pathname === href || (href !== "/admin" && pathname.startsWith(`${href}/`));
}

/** Aktiver Eintrag = längster passender Pfad (/admin/security/events schlägt /admin/security). */
export function findActiveAdminLink(groups: AdminNavGroup[], pathname: string): { group: AdminNavGroup | null; link: AdminNavLink } | null {
  let best: { group: AdminNavGroup | null; link: AdminNavLink } | null = null;
  const candidates: Array<{ group: AdminNavGroup | null; link: AdminNavLink }> = [
    ...groups.flatMap((group) => group.links.map((link) => ({ group, link }))),
    ...ADMIN_EXTRA_LINKS.map((link) => ({ group: null, link })),
  ];
  for (const candidate of candidates) {
    if (matches(candidate.link.href, pathname) && (!best || candidate.link.href.length > best.link.href.length)) best = candidate;
  }
  return best;
}

export type AdminBreadcrumb = { groupTitleKey: string | null; link: AdminNavLink | null; /** Pfad liegt unter dem Eintrag (Detailseite) */ nested: boolean };

export function adminBreadcrumb(groups: AdminNavGroup[], pathname: string): AdminBreadcrumb {
  const active = findActiveAdminLink(groups, pathname);
  if (!active || active.link.href === "/admin") return { groupTitleKey: null, link: null, nested: false };
  return { groupTitleKey: active.group?.titleKey ?? null, link: active.link, nested: pathname !== active.link.href };
}

/** Zähler einer Gruppe: der Gruppen-Badge (falls gesetzt), sonst keiner. */
export function groupCount(group: AdminNavGroup, counts: AdminNavCounts | null): number | null {
  if (!group.badge || !counts) return null;
  const value = counts[group.badge];
  return typeof value === "number" && value > 0 ? value : null;
}

/** Zähler eines Eintrags; Mandanten zeigen auch 0 nicht (nur Gesamtzahl > 0), Warteschlangen nur > 0. */
export function linkCount(link: AdminNavLink, counts: AdminNavCounts | null): number | null {
  if (!link.badge || !counts) return null;
  const value = counts[link.badge];
  return typeof value === "number" && value > 0 ? value : null;
}

/** Status-Punkt eines Eintrags (null = kein Punkt, auch bei unbekanntem Wert). */
export function linkStatus(link: AdminNavLink, counts: AdminNavCounts | null): AdminNavStatus | null {
  if (!link.status || !counts) return null;
  const value = counts[link.status];
  return value === "running" || value === "warning" || value === "critical" ? value : null;
}

/** Zähler, die Aufmerksamkeit verlangen (Glocke in der Kopfleiste). */
export function attentionItems(counts: AdminNavCounts | null, role: AdminRole | null | undefined): Array<{ key: AdminNavCountKey; count: number; href: string }> {
  if (!counts) return [];
  const items: Array<{ key: AdminNavCountKey; count: number; href: string }> = [];
  const push = (key: AdminNavCountKey, href: string) => {
    const value = counts[key];
    if (typeof value === "number" && value > 0) items.push({ key, count: value, href });
  };
  push("verifications_open", "/admin/verifications");
  push("security_alerts", role === "owner" ? "/admin/security/alerts" : "/admin/security");
  push("operations_problems", role === "owner" ? "/admin/system" : "/admin");
  return items;
}

// ── Einklappbare Bereiche (1.5.1, wie die Mandanten-Sidebar app-shell.tsx) ─────────────────
// Immer höchstens ein Bereich offen (Akkordeon), damit die Sidebar bei 1440×700 nicht scrollt.
// Die aktive Seite öffnet ihren Bereich automatisch; ohne aktiven Bereich (Übersicht, Profil) bleibt
// der zuletzt von Hand geöffnete offen (im Browser gemerkt, ADMIN_NAV_GROUP_KEY).

export const ADMIN_NAV_GROUP_KEY = "hocx-admin-nav-group";

/** Bereich der aktiven Seite (Gruppen ohne Titel, z. B. «Übersicht», sind nie einklappbar). */
export function activeAdminGroupId(groups: AdminNavGroup[], pathname: string): string | null {
  const active = findActiveAdminLink(groups, pathname);
  return active?.group && active.group.titleKey ? active.group.id : null;
}

/** Offener Bereich nach einer Navigation: aktiver Bereich, sonst der gemerkte (falls es ihn gibt). */
export function resolveOpenAdminGroup(groups: AdminNavGroup[], pathname: string, stored: string | null): string | null {
  const active = activeAdminGroupId(groups, pathname);
  if (active) return active;
  return stored && groups.some((group) => group.id === stored && group.titleKey) ? stored : null;
}

/** Klick auf einen Bereichskopf: öffnen (andere schliessen) oder den offenen schliessen. */
export function toggleAdminGroup(open: string | null, groupId: string): string | null {
  return open === groupId ? null : groupId;
}
