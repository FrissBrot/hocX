"use client";

import Link from "next/link";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { SessionInfo, TenantMembership } from "@/types/api";

import { buildNav, formatRoleLabel } from "@/components/ui/app-shell-nav";
import { ToastProvider } from "@/contexts/toast-context";
import { ProfileModal } from "@/components/ui/profile-modal";
import { TenantSelectorModal } from "@/components/ui/tenant-selector-modal";
import { TenantSettingsModal } from "@/components/ui/tenant-settings-modal";

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
  const tenantPromptCheckedRef = useRef(false);
  const [themePreference, setThemePreference] = useState<"light" | "dark" | "auto">("auto");
  const [themeReady, setThemeReady] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [edgeSidebarOpen, setEdgeSidebarOpen] = useState(false);
  const [compactFooterEnabled, setCompactFooterEnabled] = useState(false);
  const [compactFooterOpen, setCompactFooterOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [tenantSettingsModalOpen, setTenantSettingsModalOpen] = useState(false);
  const [tenantSettingsTenantId, setTenantSettingsTenantId] = useState<number | null>(null);
  const [tenantSettingsTenantName, setTenantSettingsTenantName] = useState("");
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
    const activeGroupTitle = navGroups.find((group) =>
      group.links.some((link) => pathname === link.href || pathname.startsWith(`${link.href}/`))
    )?.title;
    setExpandedGroups(
      Object.fromEntries(navGroups.map((group) => [group.title, group.title === activeGroupTitle]))
    );
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
          // Explicit "not logged in" from the server → redirect.
          router.replace("/login");
          return;
        }
        setSession(current);
        setLanguage(current.user?.preferred_language ?? "de");
        setSessionStatus("Ready");
      } catch {
        // Transient errors (network hiccup, backend 500, timeout) must NOT log
        // the user out. The session endpoint always returns HTTP 200 — a throw
        // here means a real infrastructure problem, not an expired session.
        // If the user truly has no session the server-side requireSession() will
        // have already redirected them before this component even mounts.
        if (!cancelled) {
          setSessionStatus("Ready");
        }
      }
    }

    void loadSession();
    return () => {
      cancelled = true;
    };
  }, [initialSession, router]);

  useEffect(() => {
    if (!session || tenantPromptCheckedRef.current) {
      return;
    }
    tenantPromptCheckedRef.current = true;
    const alreadyPrompted = window.sessionStorage.getItem("hocx-tenant-prompted");
    const hasMultipleTenants = session.available_tenants.length > 1;
    const hasNoDefault = session.user?.default_tenant_id == null;
    if (hasMultipleTenants && hasNoDefault && !alreadyPrompted) {
      window.sessionStorage.setItem("hocx-tenant-prompted", "1");
      setTenantModalOpen(true);
    }
  }, [session]);

  const activeLabel = useMemo(() => {
    for (const group of navGroups) {
      for (const link of group.links) {
        if (pathname === link.href || pathname.startsWith(`${link.href}/`)) {
          return link.label;
        }
      }
    }
    return "Dashboard";
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

  function openTenantSettings(membership: TenantMembership) {
    setTenantSettingsTenantId(membership.tenant_id);
    setTenantSettingsTenantName(membership.tenant_name);
    setTenantModalOpen(false);
    setTenantSettingsModalOpen(true);
  }

  async function setDefaultTenant(tenantId: number | null) {
    // Optimistic update: the PATCH result already tells us the new value, no need
    // to wait for a second round-trip (GET /api/auth/session) before the checkbox reacts.
    setSession((current) => (current?.user ? { ...current, user: { ...current.user, default_tenant_id: tenantId } } : current));
    try {
      await browserApiFetch("/api/users/me", {
        method: "PATCH",
        body: JSON.stringify({ default_tenant_id: tenantId })
      });
    } catch {
      // resync with the server if the update actually failed
      const refreshed = await browserApiFetch<SessionInfo>("/api/auth/session");
      setSession(refreshed);
    }
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
    window.sessionStorage.removeItem("hocx-tenant-prompted");
    router.replace("/login");
  }

  return (
    <ToastProvider>
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
              <div className="eyebrow">hocX</div>
              <h2 className="sidebar-title">Protokoll Studio</h2>
            </div>
          </div>
          <p className="muted sidebar-copy" ref={sidebarCopyRef}>Protokolle, Vorlagen, Termine und Exporte verwalten.</p>
          <nav className="sidebar-nav" ref={sidebarNavRef}>
            {navGroups.map((group) => (
              <div className="nav-group" key={group.title}>
                <button
                  type="button"
                  className="nav-group-toggle"
                  onClick={() =>
                    setExpandedGroups((current) => {
                      const isOpen = current[group.title];
                      const allClosed = Object.fromEntries(navGroups.map((g) => [g.title, false]));
                      return isOpen ? allClosed : { ...allClosed, [group.title]: true };
                    })
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
            <h1 className="topbar-title">{activeLabel}</h1>
          </header>
          <div className="shell-content">{children}</div>
        </div>
      </div>

      <TenantSelectorModal
        open={tenantModalOpen}
        onClose={() => setTenantModalOpen(false)}
        session={session}
        onSelect={(membership) => void switchTenant(membership)}
        onOpenSettings={openTenantSettings}
        onSetDefault={(tenantId) => void setDefaultTenant(tenantId)}
      />

      <TenantSettingsModal
        open={tenantSettingsModalOpen}
        onClose={() => setTenantSettingsModalOpen(false)}
        tenantId={tenantSettingsTenantId}
        tenantName={tenantSettingsTenantName}
        onSaved={() => router.refresh()}
      />

      <ProfileModal
        open={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
        language={language}
        onLanguageChange={setLanguage}
        onSave={() => void saveProfile()}
        onLogout={() => void logout()}
      />
    </main>
    </ToastProvider>
  );
}
