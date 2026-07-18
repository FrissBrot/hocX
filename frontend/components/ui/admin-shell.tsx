"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { ToastProvider } from "@/contexts/toast-context";
import { AdminSessionInfo } from "@/types/api";

const navLinks = [
  { href: "/admin", label: "Dashboard" },
  { href: "/admin/tenants", label: "Mandanten" },
  { href: "/admin/users", label: "Benutzer" },
  { href: "/admin/admins", label: "Admin-Accounts" },
];

export function AdminShell({ children, session }: { children: ReactNode; session: AdminSessionInfo }) {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    await browserApiFetch("/api/admin/auth/logout", { method: "POST" });
    router.replace("/admin/login");
  }

  return (
    <ToastProvider>
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
                  <Link href={link.href as any} key={link.href} className={isActive ? "nav-link nav-link-active" : "nav-link"}>
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
          </div>
        </aside>
        <div className="shell-main">
          <header className="topbar">
            <h1 className="topbar-title">Platform-Admin</h1>
          </header>
          <div className="shell-content">{children}</div>
        </div>
      </div>
    </main>
    </ToastProvider>
  );
}
