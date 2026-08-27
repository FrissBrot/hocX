"use client";

import Link from "next/link";
import type { Route } from "next";
import { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { ToastProvider } from "@/contexts/toast-context";
import { ConfirmProvider } from "@/contexts/confirm-context";
import { AdminSessionInfo } from "@/types/api";
import { CopyrightNotice } from "@/components/ui/copyright-notice";

const navLinks = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/tenants", label: "Mandanten" },
  { href: "/admin/users", label: "Benutzer" },
  { href: "/admin/domains", label: "Domains" },
  { href: "/admin/error-logs", label: "Fehlerprotokoll" },
  { href: "/admin/admins", label: "Admin-Accounts" },
  { href: "/admin/sso", label: "SSO" },
  { href: "/admin/security", label: "Sicherheit" },
];

export function AdminShell({ children, session }: { children: ReactNode; session: AdminSessionInfo }) {
  const pathname = usePathname();
  const router = useRouter();
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
        <aside className="sidebar">
          <div className="brand-lockup">
            <div className="brand-mark">hX</div>
            <div>
              <div className="eyebrow">hocX</div>
              <h2 className="sidebar-title">Platform-Admin</h2>
            </div>
          </div>
          <p className="muted sidebar-copy">Mandanten und Benutzer über das ganze System verwalten.</p>
          <nav className="sidebar-nav">
            <div className="nav-links">
              {navLinks.map((link) => {
                const isActive = pathname === link.href || (link.href !== "/admin" && pathname.startsWith(`${link.href}/`));
                return (
                  <Link href={link.href as Route} key={link.href} className={isActive ? "nav-link nav-link-active" : "nav-link"}>
                    {link.label}
                  </Link>
                );
              })}
            </div>
          </nav>
          <div className="sidebar-footer">
            <div className="identity-panel">
              <div className="identity-card">
                <div className="identity-button">
                  <div className="identity-avatar identity-avatar-user">
                    <span>{session.admin?.display_name?.slice(0, 1) ?? "A"}</span>
                  </div>
                  <div>
                    <div className="identity-heading">
                      <span className="eyebrow">Admin</span>
                    </div>
                    <strong>{session.admin?.display_name ?? "..."}</strong>
                    <div className="identity-subtle">{session.admin?.email}</div>
                  </div>
                </div>
                <button type="button" className="button-ghost" onClick={() => void logout()}>
                  Logout
                </button>
              </div>
            </div>
            <CopyrightNotice />
          </div>
        </aside>
        <div className="shell-main">
          <header className="topbar">
            <h1 className="topbar-title">Platform-Admin</h1>
          </header>
          {isReadOnlyAdmin && (
            <div
              className="admin-readonly-banner"
              style={{
                background: "var(--sev-medium-soft, #f8f0d8)",
                color: "var(--sev-medium, #8a6d0a)",
                borderBottom: "1px solid var(--border, #d8dee9)",
                padding: "8px 24px",
                fontSize: "13.5px",
                fontWeight: 500,
              }}
            >
              Nur-Lesezugriff (support): Änderungen sind mit diesem Account nicht möglich.
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
