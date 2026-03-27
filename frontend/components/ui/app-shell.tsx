"use client";

import Link from "next/link";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { SessionInfo, TenantMembership } from "@/types/api";

import { Modal } from "@/components/ui/modal";

type NavLink = { href: string; label: string };
type NavGroup = { title: string; links: NavLink[] };

function formatRoleLabel(role: string | null | undefined) {
  switch (role) {
    case "superadmin":
      return "Superadmin";
    case "admin":
      return "Admin";
    case "writer":
      return "Writer";
    case "reader":
      return "Reader";
    default:
      return role ?? "Status";
  }
}

function buildNav(session: SessionInfo | null): NavGroup[] {
  const canAdmin = !!session?.user && (session.user.is_superadmin || session.current_role === "admin");

  return [
    {
      title: "Workspace",
      links: [
        { href: "/", label: "Dashboard" },
        { href: "/protocols", label: "Protocols" }
      ]
    },
    ...(canAdmin
      ? [
          {
            title: "Structure",
            links: [
              { href: "/templates", label: "Templates" },
              { href: "/elements", label: "Elements" }
            ]
          },
          {
            title: "Administration",
            links: [
              { href: "/users", label: "Users" },
              { href: "/tenants", label: "Tenants" },
              { href: "/settings", label: "Document Templates" }
            ]
          }
        ]
      : [])
  ];
}

export function AppShell({ children, initialSession = null }: { children: ReactNode; initialSession?: SessionInfo | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const [themePreference, setThemePreference] = useState<"light" | "dark" | "auto">("auto");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [language, setLanguage] = useState("de");
  const [sessionStatus, setSessionStatus] = useState(initialSession?.authenticated ? "Ready" : "Loading workspace...");

  const navGroups = useMemo(() => buildNav(session), [session]);

  useEffect(() => {
    const storedTheme = window.localStorage.getItem("hocx-theme");
    const nextPreference = storedTheme === "dark" || storedTheme === "light" || storedTheme === "auto" ? storedTheme : "auto";
    setThemePreference(nextPreference);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const nextTheme = themePreference === "auto" ? (media.matches ? "dark" : "light") : themePreference;
      document.documentElement.dataset.theme = nextTheme;
    };

    applyTheme();
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [themePreference]);

  useEffect(() => {
    const initialGroups = Object.fromEntries(
      navGroups.map((group) => [
        group.title,
        group.links.some((link) => pathname === link.href || pathname.startsWith(`${link.href}/`))
      ])
    );
    setExpandedGroups((current) => ({ ...initialGroups, ...current }));
  }, [navGroups, pathname]);

  useEffect(() => {
    let cancelled = false;

    async function loadSession() {
      try {
        const current = await browserApiFetch<SessionInfo>("/api/auth/session");
        if (cancelled) {
          return;
        }
        if (!current.authenticated) {
          router.replace("/login");
          return;
        }
        setSession(current);
        setLanguage(current.user?.preferred_language ?? "de");
        setSessionStatus("Ready");
      } catch {
        if (!cancelled) {
          router.replace("/login");
        }
      }
    }

    void loadSession();
    return () => {
      cancelled = true;
    };
  }, [initialSession, router]);

  const activeLabel = useMemo(() => {
    for (const group of navGroups) {
      for (const link of group.links) {
        if (pathname === link.href || pathname.startsWith(`${link.href}/`)) {
          return link.label;
        }
      }
    }
    return "Workspace";
  }, [navGroups, pathname]);

  const userFullName = [session?.user?.first_name, session?.user?.last_name].filter(Boolean).join(" ");
  const userSecondaryLine =
    session?.user && userFullName && userFullName !== session.user.display_name ? userFullName : "Profil & Sprache";

  function selectTheme(nextTheme: "light" | "dark" | "auto") {
    setThemePreference(nextTheme);
    window.localStorage.setItem("hocx-theme", nextTheme);
  }

  async function switchTenant(membership: TenantMembership) {
    await browserApiFetch(`/api/auth/select-tenant/${membership.tenant_id}`, { method: "POST" });
    setTenantModalOpen(false);
    router.refresh();
  }

  async function saveProfile() {
    await browserApiFetch("/api/users/me", {
      method: "PATCH",
      body: JSON.stringify({
        preferred_language: language
      })
    });
    const refreshed = await browserApiFetch<SessionInfo>("/api/auth/session");
    setSession(refreshed);
    setProfileModalOpen(false);
    router.refresh();
  }

  async function logout() {
    await browserApiFetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  return (
    <main className="app-frame">
      <div className="shell">
        <aside className={`sidebar${mobileNavOpen ? " sidebar-open" : ""}`}>
          <div className="brand-lockup">
            <div className="brand-mark">hX</div>
            <div>
              <div className="eyebrow">hocX workspace</div>
              <h2 className="sidebar-title">Protocol Studio</h2>
            </div>
          </div>
          <p className="muted sidebar-copy">A focused workspace for tenants, protocols, templates and exports.</p>
          <nav className="sidebar-nav">
            {navGroups.map((group) => (
              <div className="nav-group" key={group.title}>
                <button
                  type="button"
                  className="nav-group-toggle"
                  onClick={() =>
                    setExpandedGroups((current) => ({
                      ...current,
                      [group.title]: !current[group.title]
                    }))
                  }
                >
                  <span className="nav-group-title">{group.title}</span>
                  <span className="nav-group-icon">{expandedGroups[group.title] ? "−" : "+"}</span>
                </button>
                {expandedGroups[group.title] ? (
                  <div className="nav-links">
                    {group.links.map((link) => {
                      const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
                      return (
                        <Link
                          href={link.href}
                          key={link.href}
                          className={isActive ? "nav-link nav-link-active" : "nav-link"}
                          onClick={() => setMobileNavOpen(false)}
                        >
                          {link.label}
                        </Link>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <div className="theme-panel">
              <div className="eyebrow">Darstellung</div>
              <div className="field-label">Farbmodus</div>
              <div className="theme-switcher">
                <button type="button" className={`theme-switch-button${themePreference === "light" ? " theme-switch-button-active" : ""}`} onClick={() => selectTheme("light")}>
                  Hell
                </button>
                <button type="button" className={`theme-switch-button${themePreference === "dark" ? " theme-switch-button-active" : ""}`} onClick={() => selectTheme("dark")}>
                  Dunkel
                </button>
                <button
                  type="button"
                  className={`theme-switch-button theme-switch-icon${themePreference === "auto" ? " theme-switch-button-active" : ""}`}
                  onClick={() => selectTheme("auto")}
                  aria-label="Auto"
                  title="Auto"
                >
                  ◐
                </button>
              </div>
            </div>

            <div className="identity-panel">
              <div className="identity-card">
                <button type="button" className="identity-button" onClick={() => setTenantModalOpen(true)}>
                  <div className="identity-avatar">
                    {session?.current_tenant?.profile_image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={session.current_tenant.profile_image_url} alt={session.current_tenant.name} />
                    ) : (
                      <span>{session?.current_tenant?.name?.slice(0, 1) ?? "T"}</span>
                    )}
                  </div>
                  <div>
                    <div className="identity-heading">
                      <span className="eyebrow">Mandant</span>
                      <span className="identity-role-pill">{formatRoleLabel(session?.current_role) || sessionStatus}</span>
                    </div>
                    <strong>{session?.current_tenant?.name ?? "..."}</strong>
                    <div className="identity-subtle">Aktiver Arbeitsbereich</div>
                  </div>
                </button>
              </div>

              <div className="identity-card">
                <button type="button" className="identity-button" onClick={() => setProfileModalOpen(true)}>
                  <div className="identity-avatar identity-avatar-user">
                    <span>{session?.user?.display_name?.slice(0, 1) ?? "U"}</span>
                  </div>
                  <div>
                    <div className="identity-heading">
                      <span className="eyebrow">Benutzer</span>
                    </div>
                    <strong>{session?.user?.display_name ?? "..."}</strong>
                    <div className="identity-subtle">{session?.user ? userSecondaryLine : sessionStatus}</div>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </aside>
        <div className="shell-main">
          <header className="topbar">
            <div>
              <div className="eyebrow">Current space</div>
              <h1 className="topbar-title">{activeLabel}</h1>
            </div>
            <div className="topbar-actions">
              <button type="button" className="button-ghost mobile-nav-toggle" onClick={() => setMobileNavOpen((current) => !current)}>
                {mobileNavOpen ? "Close menu" : "Menu"}
              </button>
            </div>
          </header>
          <div className="shell-content">{children}</div>
        </div>
      </div>

      <Modal
        open={tenantModalOpen}
        onClose={() => setTenantModalOpen(false)}
        title="Mandant wechseln"
        description="Wähle den Arbeitsbereich, in dem du gerade arbeiten möchtest."
      >
        <div className="selection-list">
          {session?.available_tenants.map((membership) => (
            <button key={membership.tenant_id} type="button" className="selection-item" onClick={() => void switchTenant(membership)}>
              <div>
                <strong>{membership.tenant_name}</strong>
                <div className="muted">{membership.role_code}</div>
              </div>
              <span className="pill">{membership.tenant_id === session.current_tenant?.id ? "Aktiv" : "Wechseln"}</span>
            </button>
          ))}
        </div>
      </Modal>

      <Modal
        open={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
        title="Benutzerprofil"
        description="Passe deine Sprache an oder melde dich ab."
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Sprache</span>
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="de">Deutsch</option>
              <option value="en">English</option>
              <option value="fr">Français</option>
              <option value="it">Italiano</option>
            </select>
          </label>
          <div className="table-actions table-actions-start">
            <button type="button" className="button-inline" onClick={() => void saveProfile()}>
              Profil speichern
            </button>
            <button type="button" className="button-inline button-danger" onClick={() => void logout()}>
              Logout
            </button>
          </div>
        </div>
      </Modal>
    </main>
  );
}
