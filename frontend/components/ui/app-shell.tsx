"use client";

import Link from "next/link";
import type { Route } from "next";
import { ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { attemptBridgeRedirect } from "@/lib/bridge-redirect";
import { browserApiFetch } from "@/lib/api/client";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { SessionInfo, TenantMembership } from "@/types/api";

import { buildNav, formatRoleLabel } from "@/components/ui/app-shell-nav";
import { NavIcon } from "@/components/ui/nav-icons";
import { ToastProvider, useToast } from "@/contexts/toast-context";
import { ConfirmProvider } from "@/contexts/confirm-context";
import { ProfileModal } from "@/components/ui/profile-modal";
import { TenantSelectorModal } from "@/components/ui/tenant-selector-modal";
import { Menu, MenuDivider, MenuItem, Popover } from "@/components/ui/popover";
import { ConnectivityStatus } from "@/components/ui/connectivity-status";
import { CopyrightNotice } from "@/components/ui/copyright-notice";

// Login rendert nie auf einer Mandanten-Custom-Domain — von dort muss eine volle Navigation
// (nicht SPA-Routing) zur Hauptdomain erfolgen, sonst gäbe es dort keine Login-Seite zu zeigen.
function redirectToLogin(router: ReturnType<typeof useRouter>): void {
  const mainDomain = getRuntimeConfig().mainAppDomain;
  if (mainDomain && window.location.hostname !== mainDomain) {
    // `from` laesst die Login-Seite den Mandanten anhand der Domain automatisch waehlen.
    window.location.href = `https://${mainDomain}/login?from=${encodeURIComponent(window.location.hostname)}`;
    return;
  }
  router.replace("/login");
}

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
  return (
    <ToastProvider>
      <ConfirmProvider>
        <AppShellInner initialSession={initialSession}>{children}</AppShellInner>
      </ConfirmProvider>
    </ToastProvider>
  );
}

// Split out from AppShell so useToast() (which requires being rendered *inside*
// ToastProvider) is actually available here - AppShell itself only sets up the
// provider and isn't a descendant of it.
function AppShellInner({ children, initialSession = null }: { children: ReactNode; initialSession?: SessionInfo | null }) {
  const showToast = useToast();
  const pathname = usePathname();
  const router = useRouter();
  const avatarTriggerRef = useRef<HTMLButtonElement | null>(null);
  const tenantPromptCheckedRef = useRef(false);
  const [themePreference, setThemePreference] = useState<"light" | "dark" | "auto">("auto");
  const [themeReady, setThemeReady] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [tenantModalOpen, setTenantModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [protocolExitAnimation, setProtocolExitAnimation] = useState(false);
  const [language, setLanguage] = useState("de");
  const [protocolAccordionEnabled, setProtocolAccordionEnabled] = useState(true);
  const [sessionStatus, setSessionStatus] = useState(initialSession?.authenticated ? "Ready" : "Loading workspace...");

  const navGroups = useMemo(() => buildNav(session), [session]);
  const activeNavGroup = useMemo(
    () => navGroups.find((group) => group.links.some((link) => pathname === link.href || pathname.startsWith(`${link.href}/`)))?.title ?? null,
    [navGroups, pathname]
  );
  const [expandedNavGroup, setExpandedNavGroup] = useState<string | null>(null);
  const isProtocolWriting = pathname.startsWith("/protocols/") && pathname !== "/protocols";

  useEffect(() => {
    setExpandedNavGroup(activeNavGroup);
  }, [activeNavGroup, pathname]);

  const previousProtocolWritingRef = useRef(isProtocolWriting);
  useLayoutEffect(() => {
    const wasProtocolWriting = previousProtocolWritingRef.current;
    previousProtocolWritingRef.current = isProtocolWriting;

    if (!isProtocolWriting && wasProtocolWriting) {
      setProtocolExitAnimation(true);
      const timer = window.setTimeout(() => setProtocolExitAnimation(false), 240);
      return () => window.clearTimeout(timer);
    }

    setProtocolExitAnimation(false);
  }, [isProtocolWriting]);

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
    setAvatarMenuOpen(false);
  }, [pathname]);

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
          redirectToLogin(router);
          return;
        }
        if (current.bridge_redirect_url && attemptBridgeRedirect(current.bridge_redirect_url)) {
          return;
        }
        setSession(current);
        setLanguage(current.user?.preferred_language ?? "de");
        setProtocolAccordionEnabled(current.user?.protocol_accordion_enabled ?? true);
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
    // Auf einer Mandanten-Custom-Domain ist der Mandant durch die Domain bereits festgelegt -
    // dort macht ein "welcher Mandant?"-Popup keinen Sinn, nur auf der Hauptdomain zeigen.
    const mainDomain = getRuntimeConfig().mainAppDomain;
    const isMainDomain = !mainDomain || window.location.hostname === mainDomain;
    const alreadyPrompted = window.sessionStorage.getItem("hocx-tenant-prompted");
    const hasMultipleTenants = session.available_tenants.length > 1;
    const hasNoDefault = session.user?.default_tenant_id == null;
    if (isMainDomain && hasMultipleTenants && hasNoDefault && !alreadyPrompted) {
      window.sessionStorage.setItem("hocx-tenant-prompted", "1");
      setTenantModalOpen(true);
    }
  }, [session]);

  const activeCrumb = useMemo(() => {
    for (const group of navGroups) {
      for (const link of group.links) {
        if (pathname === link.href || pathname.startsWith(`${link.href}/`)) {
          return { group: group.title, label: link.label };
        }
      }
    }
    return { group: "Übersicht", label: "Dashboard" };
  }, [navGroups, pathname]);

  const tenantName = session?.current_tenant?.name ?? "Mandant";
  const userInitial = session?.user?.display_name?.slice(0, 1) ?? "U";
  const roleLabel = formatRoleLabel(session?.current_role) || sessionStatus;

  function selectTheme(nextTheme: "light" | "dark" | "auto") {
    setThemePreference(nextTheme);
    window.localStorage.setItem("hocx-theme", nextTheme);
    document.documentElement.dataset.themePreference = nextTheme;
  }

  async function switchTenant(membership: TenantMembership) {
    try {
      const result = await browserApiFetch<SessionInfo>(`/api/auth/select-tenant/${membership.tenant_id}`, { method: "POST" });
      setTenantModalOpen(false);
      if (result.bridge_redirect_url && attemptBridgeRedirect(result.bridge_redirect_url)) {
        return;
      }
      // Hard reload, not router.refresh() - a soft refresh only re-fetches server data, it doesn't
      // reliably reset every client component's own state for the new tenant context, which is
      // why the switch sometimes only visibly "took" after an extra click/navigation.
      window.location.reload();
    } catch {
      showToast("Mandant konnte nicht gewechselt werden.", "error");
    }
  }

  function openTenantSettings(membership: TenantMembership) {
    setTenantModalOpen(false);
    router.push(`/tenant-settings?tenantId=${membership.tenant_id}`);
  }

  async function setDefaultTenant(tenantId: string | null) {
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
    try {
      await browserApiFetch("/api/users/me", {
        method: "PATCH",
        body: JSON.stringify({
          preferred_language: language,
          protocol_accordion_enabled: protocolAccordionEnabled,
        })
      });
      const refreshed = await browserApiFetch<SessionInfo>("/api/auth/session");
      setSession(refreshed);
      setProfileModalOpen(false);
      router.refresh();
    } catch {
      showToast("Profil konnte nicht gespeichert werden.", "error");
    }
  }

  async function logout() {
    try {
      await browserApiFetch("/api/auth/logout", { method: "POST" });
      window.sessionStorage.removeItem("hocx-tenant-prompted");
      redirectToLogin(router);
    } catch {
      showToast("Abmelden fehlgeschlagen. Bitte erneut versuchen.", "error");
    }
  }

  return (
    <main className={`app-frame${isProtocolWriting ? " app-frame-writing" : ""}${protocolExitAnimation ? " app-frame-protocol-exit" : ""}`}>
      <ConnectivityStatus />
      <div className="shell">
        {isProtocolWriting && (
          <div
            className="sidebar-edge-trigger"
            aria-hidden="true"
            onMouseEnter={() => setMobileNavOpen(true)}
          />
        )}
        {mobileNavOpen && (
          <div className="sidebar-overlay" aria-hidden="true" onClick={() => setMobileNavOpen(false)} />
        )}
        <aside
          className={`sidebar${mobileNavOpen ? " sidebar-open" : ""}${isProtocolWriting ? " sidebar-writing" : ""}`}
          onMouseLeave={() => {
            // In protocol writing, the sidebar is a temporary overlay opened from either
            // the left-edge hotspot or the menu button.
            if (isProtocolWriting && mobileNavOpen) {
              setMobileNavOpen(false);
            }
          }}
        >
          <button type="button" className="brand-lockup brand-lockup-trigger" onClick={() => setTenantModalOpen(true)}>
            <div className="brand-mark">hX</div>
            <div className="brand-lockup-text">
              <div className="sidebar-wordmark">hocX</div>
              <div className="sidebar-tenant-name">{tenantName}</div>
            </div>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" width={16} height={16} aria-hidden="true" className="brand-lockup-chevron">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
          <nav className="sidebar-nav">
            {navGroups.map((group) => {
              const isExpanded = expandedNavGroup === group.title;
              return (
                <div className={`nav-group${isExpanded ? " nav-group-expanded" : ""}`} key={group.title}>
                  <button
                    type="button"
                    className="nav-group-label"
                    aria-expanded={isExpanded}
                    onClick={() => setExpandedNavGroup(group.title)}
                  >
                    <span>{group.title}</span>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" width={14} height={14} aria-hidden="true">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </button>
                  {isExpanded && (
                    <div className="nav-links">
                      {group.links.map((link) => {
                        const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
                        return (
                          <Link
                            href={link.href as Route}
                            key={link.href}
                            className={isActive ? "nav-link nav-link-active" : "nav-link"}
                            onClick={() => setMobileNavOpen(false)}
                          >
                            <NavIcon name={link.icon} className="nav-link-icon" />
                            <span className="nav-link-label">{link.label}</span>
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
          <div className="sidebar-footer">
            <div className="identity-panel">
              <div className="identity-card">
                <button
                  ref={avatarTriggerRef}
                  type="button"
                  className="identity-button"
                  aria-haspopup="menu"
                  aria-expanded={avatarMenuOpen}
                  onClick={() => setAvatarMenuOpen((current) => !current)}
                >
                  <div className="identity-avatar identity-avatar-user">
                    <span>{userInitial}</span>
                  </div>
                  <div>
                    <strong>{session?.user?.display_name ?? "..."}</strong>
                    <div className="identity-subtle">{roleLabel}</div>
                  </div>
                </button>
              </div>
            </div>
            <CopyrightNotice />
          </div>
        </aside>
        <div className="shell-main">
          <header className="topbar">
            <div className="topbar-actions">
              <button type="button" className="button-ghost mobile-nav-toggle" onClick={() => setMobileNavOpen((current) => !current)}>
                {mobileNavOpen ? "Schliessen" : "☰"}
              </button>
            </div>
            <div className="topbar-breadcrumb">
              <span className="topbar-breadcrumb-group">{activeCrumb.group}</span>
              <span className="topbar-breadcrumb-sep">/</span>
              <span className="topbar-breadcrumb-page">{activeCrumb.label}</span>
            </div>
            <Popover open={avatarMenuOpen} onOpenChange={setAvatarMenuOpen} anchorRef={avatarTriggerRef} align="start">
              <Menu>
                <div className="menu-header">
                  <div className="menu-header-name">{session?.user?.display_name ?? "..."}</div>
                  <div className="menu-header-role">{roleLabel}</div>
                </div>
                <MenuDivider />
                <MenuItem
                  onSelect={() => {
                    setAvatarMenuOpen(false);
                    setProfileModalOpen(true);
                  }}
                >
                  Profil bearbeiten
                </MenuItem>
                <MenuItem
                  onSelect={() => {
                    setAvatarMenuOpen(false);
                    setTenantModalOpen(true);
                  }}
                >
                  Mandant wechseln
                </MenuItem>
                <MenuDivider />
                <div className="menu-header menu-header-tight">Darstellung</div>
                <MenuItem selected={themeReady && themePreference === "light"} onSelect={() => selectTheme("light")}>
                  Hell
                </MenuItem>
                <MenuItem selected={themeReady && themePreference === "dark"} onSelect={() => selectTheme("dark")}>
                  Dunkel
                </MenuItem>
                <MenuItem selected={themeReady && themePreference === "auto"} onSelect={() => selectTheme("auto")}>
                  Automatisch
                </MenuItem>
                <MenuDivider />
                <MenuItem
                  danger
                  onSelect={() => {
                    setAvatarMenuOpen(false);
                    void logout();
                  }}
                >
                  Abmelden
                </MenuItem>
              </Menu>
            </Popover>
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

      <ProfileModal
        open={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
        language={language}
        onLanguageChange={setLanguage}
        protocolAccordionEnabled={protocolAccordionEnabled}
        onProtocolAccordionChange={setProtocolAccordionEnabled}
        onSave={() => void saveProfile()}
        onLogout={() => void logout()}
      />
    </main>
  );
}
