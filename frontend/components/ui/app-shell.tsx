"use client";

import Link from "next/link";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { SessionInfo, TenantMembership } from "@/types/api";

import { Modal } from "@/components/ui/modal";

type NavLink = { href: string; label: string };
type NavGroup = { title: string; links: NavLink[] };

function readStoredThemePreference(): "light" | "dark" | "auto" {
  if (typeof window === "undefined") {
    return "auto";
  }

  const preset = document.documentElement.dataset.themePreference;
  if (preset === "light" || preset === "dark" || preset === "auto") {
    return preset;
  }

  const storedTheme = window.localStorage.getItem("hocx-theme");
  return storedTheme === "dark" || storedTheme === "light" || storedTheme === "auto" ? storedTheme : "auto";
}

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
            title: "Datensätze",
            links: [
              { href: "/lists", label: "Listen" },
              { href: "/participants", label: "Teilnehmer" },
              { href: "/events", label: "Termine" }
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
  const sidebarRef = useRef<HTMLElement | null>(null);
  const brandLockupRef = useRef<HTMLDivElement | null>(null);
  const sidebarCopyRef = useRef<HTMLParagraphElement | null>(null);
  const sidebarNavRef = useRef<HTMLElement | null>(null);
  const compactFooterRef = useRef<HTMLDivElement | null>(null);
  const compactFooterPanelsRef = useRef<HTMLDivElement | null>(null);
  const compactFooterCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [themePreference, setThemePreference] = useState<"light" | "dark" | "auto">("auto");
  const [themeReady, setThemeReady] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [edgeSidebarOpen, setEdgeSidebarOpen] = useState(false);
  const [compactFooterEnabled, setCompactFooterEnabled] = useState(false);
  const [compactFooterOpen, setCompactFooterOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [language, setLanguage] = useState("de");
  const [sessionStatus, setSessionStatus] = useState(initialSession?.authenticated ? "Ready" : "Loading workspace...");

  const navGroups = useMemo(() => buildNav(session), [session]);
  const isProtocolWriting = pathname.startsWith("/protocols/") && pathname !== "/protocols";

  useEffect(() => {
    setThemePreference(readStoredThemePreference());
    setThemeReady(true);
  }, []);

  useEffect(() => {
    if (!themeReady) {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const nextTheme = themePreference === "auto" ? (media.matches ? "dark" : "light") : themePreference;
      document.documentElement.dataset.theme = nextTheme;
      document.documentElement.dataset.themePreference = themePreference;
    };

    applyTheme();
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [themePreference, themeReady]);

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
    setCompactFooterOpen(false);
  }, [pathname, tenantModalOpen, profileModalOpen]);

  useEffect(() => {
    if (!compactFooterOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!compactFooterRef.current?.contains(event.target as Node)) {
        setCompactFooterOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCompactFooterOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [compactFooterOpen]);

  useEffect(() => {
    return () => {
      if (compactFooterCloseTimerRef.current) {
        clearTimeout(compactFooterCloseTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const sidebar = sidebarRef.current;
    const brandLockup = brandLockupRef.current;
    const sidebarCopy = sidebarCopyRef.current;
    const sidebarNav = sidebarNavRef.current;
    const footerPanels = compactFooterPanelsRef.current;
    if (!sidebar || !brandLockup || !sidebarCopy || !sidebarNav || !footerPanels) {
      return;
    }

    let frameId = 0;
    const measureCompactFooter = () => {
      frameId = 0;
      const sidebarStyles = window.getComputedStyle(sidebar);
      const sidebarGap = Number.parseFloat(sidebarStyles.rowGap || sidebarStyles.gap || "0") || 0;
      const paddingTop = Number.parseFloat(sidebarStyles.paddingTop || "0") || 0;
      const paddingBottom = Number.parseFloat(sidebarStyles.paddingBottom || "0") || 0;
      const totalContentHeight =
        brandLockup.scrollHeight +
        sidebarCopy.scrollHeight +
        sidebarNav.scrollHeight +
        footerPanels.scrollHeight +
        paddingTop +
        paddingBottom +
        sidebarGap * 3;

      setCompactFooterEnabled(totalContentHeight > sidebar.clientHeight + 2);
    };

    const scheduleMeasure = () => {
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      frameId = window.requestAnimationFrame(measureCompactFooter);
    };

    scheduleMeasure();

    const observer = new ResizeObserver(() => scheduleMeasure());
    observer.observe(sidebar);
    observer.observe(brandLockup);
    observer.observe(sidebarCopy);
    observer.observe(sidebarNav);
    observer.observe(footerPanels);
    window.addEventListener("resize", scheduleMeasure);

    return () => {
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      observer.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
    };
  }, [expandedGroups, navGroups, pathname, session]);

  useEffect(() => {
    if (!compactFooterEnabled) {
      setCompactFooterOpen(false);
    }
  }, [compactFooterEnabled]);

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
  const tenantName = session?.current_tenant?.name ?? "Mandant";

  function renderTenantAvatar() {
    if (session?.current_tenant?.profile_image_url) {
      // eslint-disable-next-line @next/next/no-img-element
      return <img src={session.current_tenant.profile_image_url} alt={tenantName} />;
    }

    return <span>{tenantName.slice(0, 1) || "T"}</span>;
  }

  function selectTheme(nextTheme: "light" | "dark" | "auto") {
    setThemePreference(nextTheme);
    window.localStorage.setItem("hocx-theme", nextTheme);
    document.documentElement.dataset.themePreference = nextTheme;
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
    <main className={`app-frame${isProtocolWriting ? " app-frame-writing" : ""}`}>
      {isProtocolWriting ? (
        <button
          type="button"
          className={`edge-sidebar-trigger${mobileNavOpen || edgeSidebarOpen ? " edge-sidebar-trigger-hidden" : ""}`}
          aria-label="Open sidebar"
          onMouseEnter={() => setEdgeSidebarOpen(true)}
          onFocus={() => setEdgeSidebarOpen(true)}
          onClick={() => setMobileNavOpen(true)}
        >
          <span />
          <span />
          <span />
        </button>
      ) : null}
      <div className="shell">
        <aside
          ref={sidebarRef}
          className={`sidebar${mobileNavOpen || edgeSidebarOpen ? " sidebar-open" : ""}${isProtocolWriting ? " sidebar-writing" : ""}`}
          onMouseEnter={() => {
            if (isProtocolWriting) {
              setEdgeSidebarOpen(true);
            }
          }}
          onMouseLeave={() => {
            if (isProtocolWriting && !mobileNavOpen) {
              setEdgeSidebarOpen(false);
            }
          }}
        >
          <div className="brand-lockup" ref={brandLockupRef}>
            <div className="brand-mark">hX</div>
            <div>
              <div className="eyebrow">hocX workspace</div>
              <h2 className="sidebar-title">Protocol Studio</h2>
            </div>
          </div>
          <p className="muted sidebar-copy" ref={sidebarCopyRef}>A focused workspace for tenants, protocols, templates and exports.</p>
          <nav className="sidebar-nav" ref={sidebarNavRef}>
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
                          href={link.href as any}
                          key={link.href}
                          className={isActive ? "nav-link nav-link-active" : "nav-link"}
                          onClick={() => {
                            setMobileNavOpen(false);
                            setEdgeSidebarOpen(false);
                          }}
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
          <div
            className={`sidebar-footer${compactFooterEnabled ? " sidebar-footer-compact-enabled" : ""}${compactFooterOpen ? " sidebar-footer-open" : ""}`}
            ref={compactFooterRef}
            onMouseEnter={() => {
              if (compactFooterEnabled) {
                if (compactFooterCloseTimerRef.current) {
                  clearTimeout(compactFooterCloseTimerRef.current);
                  compactFooterCloseTimerRef.current = null;
                }
                setCompactFooterOpen(true);
              }
            }}
            onMouseLeave={(event) => {
              if (!compactFooterEnabled) {
                return;
              }
              const nextTarget = event.relatedTarget;
              if (!compactFooterRef.current?.contains(nextTarget as Node | null)) {
                compactFooterCloseTimerRef.current = setTimeout(() => {
                  setCompactFooterOpen(false);
                }, 150);
              }
            }}
            onFocusCapture={() => {
              if (compactFooterEnabled) {
                if (compactFooterCloseTimerRef.current) {
                  clearTimeout(compactFooterCloseTimerRef.current);
                  compactFooterCloseTimerRef.current = null;
                }
                setCompactFooterOpen(true);
              }
            }}
            onBlurCapture={(event) => {
              if (!compactFooterEnabled) {
                return;
              }
              const nextTarget = event.relatedTarget;
              if (!compactFooterRef.current?.contains(nextTarget as Node | null)) {
                compactFooterCloseTimerRef.current = setTimeout(() => {
                  setCompactFooterOpen(false);
                }, 150);
              }
            }}
          >
            <button
              type="button"
              className="sidebar-footer-trigger"
              aria-label={compactFooterOpen ? `Menü für ${tenantName} schließen` : `Menü für ${tenantName} öffnen`}
              aria-expanded={compactFooterOpen}
              aria-controls="sidebar-footer-menu"
              onClick={() => setCompactFooterOpen((current) => !current)}
            >
              <div className="identity-avatar sidebar-footer-trigger-avatar">{renderTenantAvatar()}</div>
              <span className="sidebar-footer-trigger-text">Menü</span>
              <span className="sidebar-footer-trigger-spacer" aria-hidden="true" />
            </button>

            <div className="sidebar-footer-panels" id="sidebar-footer-menu" ref={compactFooterPanelsRef}>
              <div className="theme-panel">
                <div className="eyebrow">Darstellung</div>
                <div className="field-label">Farbmodus</div>
                <div className="theme-switcher">
                  <button type="button" className={`theme-switch-button${themeReady && themePreference === "light" ? " theme-switch-button-active" : ""}`} onClick={() => selectTheme("light")}>
                    Hell
                  </button>
                  <button type="button" className={`theme-switch-button${themeReady && themePreference === "dark" ? " theme-switch-button-active" : ""}`} onClick={() => selectTheme("dark")}>
                    Dunkel
                  </button>
                  <button
                    type="button"
                    className={`theme-switch-button theme-switch-icon${themeReady && themePreference === "auto" ? " theme-switch-button-active" : ""}`}
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
                  <button
                    type="button"
                    className="identity-button"
                    onClick={() => {
                      setCompactFooterOpen(false);
                      setTenantModalOpen(true);
                    }}
                  >
                    <div className="identity-avatar">{renderTenantAvatar()}</div>
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
                  <button
                    type="button"
                    className="identity-button"
                    onClick={() => {
                      setCompactFooterOpen(false);
                      setProfileModalOpen(true);
                    }}
                  >
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
          </div>
        </aside>
        <div className="shell-main">
          <header className="topbar">
            <div className="topbar-actions">
              <button type="button" className="button-ghost mobile-nav-toggle" onClick={() => setMobileNavOpen((current) => !current)}>
                {mobileNavOpen ? "Schliessen" : "☰"}
              </button>
            </div>
            <div>
              <div className="eyebrow">Current space</div>
              <h1 className="topbar-title">{activeLabel}</h1>
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
