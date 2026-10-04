"use client";

import Link from "next/link";
import type { Route } from "next";
import { ReactNode, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";
import { ToastProvider } from "@/contexts/toast-context";
import { ConfirmProvider } from "@/contexts/confirm-context";
import { AdminSessionInfo, AdminTenantPage } from "@/types/api";
import { CopyrightNotice } from "@/components/ui/copyright-notice";

type AdminIconKey = "dashboard" | "tenants" | "pricing" | "users" | "domains" | "errors" | "pipeline" | "admins" | "sso" | "security";

type AdminNavLink = { href: string; labelKey: string; icon: AdminIconKey; badge?: "count" };

// labelKey/titleKey sind Schluessel im "adminShell"-Namespace (frontend/messages/<locale>/adminShell.json) -
// uebersetzt wird erst beim Rendern in AdminShell, siehe app-shell-nav.ts fuer dasselbe Muster.
const navGroups: { titleKey: string | null; links: AdminNavLink[] }[] = [
  { titleKey: null, links: [{ href: "/admin", labelKey: "nav.dashboard", icon: "dashboard" }] },
  {
    titleKey: "groups.tenants",
    links: [
      { href: "/admin/tenants", labelKey: "nav.tenants", icon: "tenants", badge: "count" },
      { href: "/admin/plans", labelKey: "nav.pricing", icon: "pricing" },
      { href: "/admin/users", labelKey: "nav.users", icon: "users" },
      { href: "/admin/domains", labelKey: "nav.domains", icon: "domains" },
    ],
  },
  {
    titleKey: "groups.system",
    links: [
      { href: "/admin/error-logs", labelKey: "nav.errorLogs", icon: "errors" },
      { href: "/admin/upload-pipeline", labelKey: "nav.uploadPipeline", icon: "pipeline" },
    ],
  },
  {
    titleKey: "groups.access",
    links: [
      { href: "/admin/admins", labelKey: "nav.admins", icon: "admins" },
      { href: "/admin/sso", labelKey: "nav.sso", icon: "sso" },
      { href: "/admin/security", labelKey: "nav.security", icon: "security" },
    ],
  },
];

const allNavLinks = navGroups.flatMap((group) => group.links);

function isActiveLink(href: string, pathname: string): boolean {
  return pathname === href || (href !== "/admin" && pathname.startsWith(`${href}/`));
}

/** Linienicons im Stil von nav-icons.tsx, nur für die Admin-Navigation. */
function AdminNavIcon({ name }: { name: AdminIconKey }) {
  const paths: Record<AdminIconKey, ReactNode> = {
    dashboard: (
      <>
        <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.5" />
        <rect x="13" y="3.5" width="7.5" height="7.5" rx="1.5" />
        <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.5" />
        <rect x="13" y="13" width="7.5" height="7.5" rx="1.5" />
      </>
    ),
    tenants: (
      <>
        <path d="M4 20V10l8-5.5L20 10v10" />
        <path d="M9.5 20v-6h5v6M3 20h18" />
      </>
    ),
    pricing: (
      <>
        <path d="M3.5 12.2V4.5a1 1 0 011-1h7.7l8.3 8.3a1.5 1.5 0 010 2.1l-6.4 6.4a1.5 1.5 0 01-2.1 0z" />
        <circle cx="8" cy="8" r="1.4" />
      </>
    ),
    users: (
      <>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M2.5 20c.6-3.4 3.2-5.5 6.5-5.5s5.9 2.1 6.5 5.5" />
        <path d="M15.5 4.8a3.5 3.5 0 010 6.4M18 14.8c1.9.7 3.2 2.5 3.5 5.2" />
      </>
    ),
    domains: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M3.5 12h17M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5s1.1-6.1 3.4-8.5z" />
      </>
    ),
    errors: (
      <>
        <path d="M10.3 4.2L2.8 17.5a2 2 0 001.7 3h15a2 2 0 001.7-3L13.7 4.2a2 2 0 00-3.4 0z" />
        <path d="M12 9.5v4M12 17h.01" />
      </>
    ),
    pipeline: (
      <>
        <path d="M4 7h9M17 7h3M4 17h3M11 17h9M4 12h13M21 12h-.5" />
        <circle cx="15" cy="7" r="2" />
        <circle cx="9" cy="17" r="2" />
        <circle cx="19" cy="12" r="2" />
      </>
    ),
    admins: <path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.1-7.5 9.5-4.4-1.4-7.5-4.9-7.5-9.5V6z" />,
    sso: (
      <>
        <circle cx="7.5" cy="15.5" r="4" />
        <path d="M10.4 12.6L20 3M16 7l2.5 2.5M13.5 9.5l2 2" />
      </>
    ),
    security: (
      <>
        <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
        <path d="M8 10.5V7.5a4 4 0 018 0v3" />
      </>
    ),
  };
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={18} height={18} aria-hidden="true" className="nav-link-icon">
      {paths[name]}
    </svg>
  );
}

export function AdminShell({ children, session }: { children: ReactNode; session: AdminSessionInfo }) {
  const t = useTranslations("adminShell");
  const pathname = usePathname();
  const router = useRouter();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [tenantTotal, setTenantTotal] = useState<number | null>(null);

  useEffect(() => {
    // Nur für den Zähler in der Navigation - limit=1 hält die Antwort klein.
    browserApiFetch<AdminTenantPage>("/api/admin/tenants?limit=1&offset=0")
      .then((page) => setTenantTotal(page.total))
      .catch(() => setTenantTotal(null));
  }, []);

  const activeLink = allNavLinks.find((link) => isActiveLink(link.href, pathname));
  // The backend's require_admin_write already rejects every create/update/delete for a
  // "support"-role admin with a 403 (see core/admin_security.py) - but until this fix,
  // nothing in the frontend ever read session.admin.role at all (audit finding,
  // 2026-08-25), so a support admin saw the exact same fully-interactive write UI as an
  // owner and only discovered the restriction as a confusing failed-request error deep
  // into some action. This banner makes the actual access level visible up front instead.
  const isReadOnlyAdmin = session.admin?.role === "support";

  async function logout() {
    await browserApiFetch("/api/admin/auth/logout", { method: "POST" });
    router.replace("/admin/login");
  }

  return (
    <ToastProvider>
    <ConfirmProvider>
    <main className="app-frame">
      <div className="shell">
        {mobileNavOpen && (
          <div className="sidebar-overlay" aria-hidden="true" onClick={() => setMobileNavOpen(false)} />
        )}
        <aside className={mobileNavOpen ? "sidebar sidebar-open" : "sidebar"}>
          <div className="brand-lockup">
            <div className="brand-mark">hX</div>
            <div>
              <div className="eyebrow">hocX</div>
              <h2 className="sidebar-title">{t("title")}</h2>
            </div>
          </div>
          <p className="muted sidebar-copy">{t("tagline")}</p>
          <nav className="sidebar-nav admin-sidebar-nav">
            {navGroups.map((group) => (
              <div className="admin-nav-group" key={group.titleKey ?? "root"}>
                {group.titleKey ? <div className="admin-nav-group-title">{t(group.titleKey)}</div> : null}
                <div className="nav-links">
                  {group.links.map((link) => (
                    <Link
                      href={link.href as Route}
                      key={link.href}
                      className={isActiveLink(link.href, pathname) ? "nav-link nav-link-active" : "nav-link"}
                      onClick={() => setMobileNavOpen(false)}
                    >
                      <AdminNavIcon name={link.icon} />
                      <span className="nav-link-label">{t(link.labelKey)}</span>
                      {link.badge === "count" && tenantTotal !== null ? <span className="admin-nav-count">{tenantTotal}</span> : null}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <div className="admin-identity">
              <div className="identity-avatar admin-identity-avatar">
                <span>{session.admin?.display_name?.slice(0, 1) ?? "A"}</span>
              </div>
              <div className="admin-identity-copy">
                <strong>{session.admin?.display_name ?? "..."}</strong>
                <div className="identity-subtle">{session.admin?.email}</div>
              </div>
              <button type="button" className="button-ghost admin-identity-logout" onClick={() => void logout()}>
                {t("logout")}
              </button>
            </div>
            <CopyrightNotice />
          </div>
        </aside>
        <div className="shell-main">
          <header className="topbar admin-topbar">
            <button
              type="button"
              className="button-ghost mobile-nav-toggle"
              onClick={() => setMobileNavOpen((current) => !current)}
            >
              {mobileNavOpen ? t("menuToggleClose") : "☰"}
            </button>
            <nav className="topbar-breadcrumb admin-breadcrumb" aria-label={t("breadcrumbNav")}>
              {activeLink && activeLink.href !== "/admin" ? (
                <>
                  <Link href="/admin" className="topbar-breadcrumb-group">
                    {t("title")}
                  </Link>
                  <span className="topbar-breadcrumb-sep" aria-hidden="true">/</span>
                  <span aria-current="page">{t(activeLink.labelKey)}</span>
                </>
              ) : (
                <span aria-current="page">{t("title")}</span>
              )}
            </nav>
          </header>
          {isReadOnlyAdmin && (
            <div className="admin-readonly-banner">
              {t("readOnlyBanner")}
            </div>
          )}
          <div className="shell-content">{children}</div>
        </div>
      </div>
    </main>
    </ConfirmProvider>
    </ToastProvider>
  );
}
