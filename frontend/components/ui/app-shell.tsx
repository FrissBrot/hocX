"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import type { Route } from "next";
import { ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { attemptBridgeRedirect } from "@/lib/bridge-redirect";
import { browserApiFetch } from "@/lib/api/client";
import { CONNECTIONS_HREF } from "@/lib/calendar-feeds";
import { getRuntimeConfig } from "@/lib/runtime-config";
import { SessionInfo } from "@/types/api";

import {
  activeSettingsLink,
  buildNav,
  buildSettingsNav,
  formatRoleLabel,
  isNavLinkActive,
  isSettingsPath,
  NavLink,
  relatedNavLink,
  SETTINGS_GROUP,
  SETTINGS_HREF,
} from "@/components/ui/app-shell-nav";
import { SettingsFrame, SettingsIcon, usesSettingsFrame } from "@/components/ui/settings-frame";
import { NavIcon } from "@/components/ui/nav-icons";
import { StepUpProvider } from "@/contexts/step-up-context";
import { ToastProvider, useToast } from "@/contexts/toast-context";
import { ConfirmProvider, useConfirm } from "@/contexts/confirm-context";
import { clearSimilarityGroupsCache } from "@/components/photos/use-similarity-groups";
import { clearOfflineStore, getOfflineSnapshot } from "@/lib/offline-store";
import { Menu, MenuDivider, MenuItem, menuButtonKeyDown, Popover } from "@/components/ui/popover";
import { ConnectivityStatus } from "@/components/ui/connectivity-status";
import { CopyrightNotice } from "@/components/ui/copyright-notice";
import { MobileMorePanel, MobileShellProviders, MobileTabBar } from "@/components/mobile/mobile-shell";
import { useIsMobile, useViewportEpoch } from "@/lib/hooks/use-is-mobile";
import { InstallAppPrompt } from "@/components/ui/install-app-prompt";
import { MfaGraceBanner } from "@/components/ui/mfa-grace-banner";
import { PasswordBreachedBanner } from "@/components/ui/password-breached-banner";
import { findListSearchInput } from "@/lib/search/list-search";
import { useGlobalSearchShortcuts, useShortcutLabel } from "@/lib/search/shortcuts";
import { MAIN_CONTENT_ID } from "@/lib/a11y/focus";
import { useFocusRescue } from "@/lib/a11y/use-focus-rescue";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { SkipLink } from "@/components/ui/skip-link";
import type { GlobalSearchAction } from "@/components/search/global-search";

// Globale Suche (Ctrl+K): erst beim ersten Öffnen laden.
const GlobalSearch = dynamic(() => import("@/components/search/global-search").then((m) => m.GlobalSearch), {
  ssr: false,
});

// Shortcut-Hilfe («?»): erst beim Oeffnen laden.
const ShortcutHelp = dynamic(() => import("@/components/ui/shortcut-help").then((m) => m.ShortcutHelp), { ssr: false });

// Erst beim Oeffnen laden (MFA-Verwaltung, geschuetzter Export, Sprachwahl).
const ProfileModal = dynamic(() => import("@/components/ui/profile-modal").then((m) => m.ProfileModal), {
  ssr: false,
});

// Sitzungspruefung im Browser: Jede Seite liefert die serverseitig frisch geladene Sitzung als
// initialSession mit; ein eigener Abruf von /api/auth/session ist daher nur noetig, wenn keine
// mitkam oder der letzte Abruf/die letzte Seite laenger als SESSION_STALE_MS her ist (Rueckkehr
// in einen Tab, der lange im Hintergrund lag - abgelaufene Sitzung fuehrt dann zum Login).
// Modulweit, weil AppShell bei jedem Seitenwechsel neu gemountet wird.
const SESSION_STALE_MS = 60_000;
let lastSessionCheckAt = 0;
// Ob in diesem Dokument schon einmal aus dem Browser geprüft wurde. Nur dieser Abruf sieht die
// echte Domain und kann zur Domain des Mandanten weiterleiten (Bridge); die Sitzung vom Server
// kommt ohne bridge_redirect_url (withoutBridgeRedirect in lib/api/server.ts). Ein voller
// Seitenaufruf setzt das Modul zurück, Seitenwechsel in der App nicht.
let browserSessionChecked = false;

// Login rendert nie auf einer Mandanten-Custom-Domain — von dort muss eine volle Navigation
// (nicht SPA-Routing) zur Hauptdomain erfolgen, sonst gäbe es dort keine Login-Seite zu zeigen.
const PROFILE_LINK_KEY = "hocx.profileLink";

/** Wert von ?profile= → Reiter-ID im Profil-Dialog (unbekannt: Profil). */
export function profileTabFromLink(value: string): string {
  // ?profile=security: Link «Sicherheit prüfen» aus den Sicherheitsmails (Auth-Audit 2026-11-20)
  if (value === "security") return "sicherheit";
  return value === "notifications" ? "benachrichtigungen" : "profil";
}

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
        <StepUpProvider>
          <AppShellInner initialSession={initialSession}>{children}</AppShellInner>
        </StepUpProvider>
      </ConfirmProvider>
    </ToastProvider>
  );
}

// Split out from AppShell so useToast() (which requires being rendered *inside*
// ToastProvider) is actually available here - AppShell itself only sets up the
// provider and isn't a descendant of it.
function AppShellInner({ children, initialSession = null }: { children: ReactNode; initialSession?: SessionInfo | null }) {
  const t = useTranslations("nav");
  const tSettings = useTranslations("settings");
  const confirm = useConfirm();
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const isMobile = useIsMobile();
  const viewportEpoch = useViewportEpoch();
  const pathname = usePathname();
  const router = useRouter();
  const avatarTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [themePreference, setThemePreference] = useState<"light" | "dark" | "auto">("auto");
  const [themeReady, setThemeReady] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  // «Mehr»-Panel der Mobile-Shell. Seitenwechsel und Wechsel auf Desktop schliessen es.
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const openMobileMore = useCallback(() => setMobileMoreOpen(true), []);
  useEffect(() => {
    setMobileMoreOpen(false);
  }, [pathname, isMobile]);
  const sidebarRef = useRef<HTMLElement | null>(null);
  const navToggleRef = useRef<HTMLButtonElement | null>(null);
  // Ausklappbare Seitenleiste (schmale Fenster, Schreibmodus): Escape schliesst sie und gibt den
  // Fokus an den Menü-Knopf zurück, wenn er in der Leiste stand.
  usePopupEscape(mobileNavOpen && !isMobile, () => {
    const hadFocus = sidebarRef.current?.contains(document.activeElement) ?? false;
    setMobileNavOpen(false);
    if (hadFocus) navToggleRef.current?.focus();
  }, sidebarRef);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const [session, setSession] = useState<SessionInfo | null>(initialSession);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  // Reiter beim Öffnen über einen Direktlink (?profile=notifications, z. B. aus E-Mails)
  const [profileInitialTab, setProfileInitialTab] = useState<string | undefined>(undefined);
  const [protocolExitAnimation, setProtocolExitAnimation] = useState(false);
  const [language, setLanguage] = useState("de");
  const [sessionStatus, setSessionStatus] = useState(initialSession?.authenticated ? t("sessionReady") : t("sessionLoading"));
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchListInput, setSearchListInput] = useState<HTMLInputElement | null>(null);
  const shortcut = useShortcutLabel();

  // Ctrl+K öffnet (und schliesst) die globale Suche; das Suchfeld einer Liste auf der Seite wird
  // beim Öffnen gemerkt, bevor das Suchfenster selbst der oberste Dialog ist.
  const searchOpenRef = useRef(false);
  useEffect(() => {
    searchOpenRef.current = searchOpen;
  }, [searchOpen]);
  const openSearch = useCallback(() => {
    setSearchListInput(findListSearchInput());
    setSearchOpen(true);
  }, []);
  const toggleSearch = useCallback(() => {
    if (searchOpenRef.current) setSearchOpen(false);
    else openSearch();
  }, [openSearch]);
  useGlobalSearchShortcuts(toggleSearch, session?.authenticated !== false);
  // «?» öffnet die Shortcut-Hilfe (lib/keyboard/registry.ts), verlorener Fokus landet im Inhalt
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  useShortcut("global.help", () => setShortcutHelpOpen(true), { enabled: session?.authenticated !== false });
  useFocusRescue();
  // Tippen direkt nach Ctrl+K/⌘K, bevor das Suchfeld existiert (Fenster wird nachgeladen und
  // montiert): die Zeichen sammeln und dem Feld übergeben, statt sie zu verlieren.
  const pendingSearchKeys = useRef<{ text: string; consumed: boolean }>({ text: "", consumed: true });
  useEffect(() => {
    if (!searchOpen) return;
    pendingSearchKeys.current = { text: "", consumed: false };
    function collect(event: KeyboardEvent) {
      if (pendingSearchKeys.current.consumed) return;
      if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
      if (event.target instanceof HTMLInputElement && event.target.getAttribute("role") === "combobox") return;
      if (event.key.length === 1) {
        pendingSearchKeys.current.text += event.key;
        event.preventDefault();
      } else if (event.key === "Backspace") {
        pendingSearchKeys.current.text = pendingSearchKeys.current.text.slice(0, -1);
        event.preventDefault();
      }
    }
    window.addEventListener("keydown", collect, true); // a11y-ok: kein Shortcut - puffert Tipp-Eingaben, bis das Suchfeld montiert ist
    return () => window.removeEventListener("keydown", collect, true);
  }, [searchOpen]);
  // Suchfenster im Leerlauf vorladen: beim ersten Ctrl+K/⌘K ist es sofort da, und kein
  // Tastendruck geht verloren, während der Code noch geladen wird.
  useEffect(() => {
    if (session?.authenticated === false) return;
    const preload = () => void import("@/components/search/global-search");
    const idle = (window as Window & { requestIdleCallback?: (callback: () => void) => number }).requestIdleCallback;
    if (idle) idle(preload);
    else window.setTimeout(preload, 1500);
  }, [session?.authenticated]);

  const navGroups = useMemo(() => buildNav(session), [session]);
  const settingsGroups = useMemo(() => buildSettingsNav(session), [session]);
  const inSettings = isSettingsPath(settingsGroups, pathname);
  const activeNavGroup = useMemo(
    () => navGroups.find((group) => group.links.some((link) => isNavLinkActive(link, pathname)))?.titleKey ?? null,
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

    // Wendet eine (frisch geladene oder vom Server mitgelieferte) Sitzung an.
    function applySession(current: SessionInfo) {
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
      setSessionStatus(t("sessionReady"));
    }

    async function loadSession() {
      lastSessionCheckAt = Date.now();
      browserSessionChecked = true;
      try {
        const current = await browserApiFetch<SessionInfo>("/api/auth/session");
        if (!cancelled) {
          applySession(current);
        }
      } catch {
        // Transient errors (network hiccup, backend 500, timeout) must NOT log
        // the user out. The session endpoint always returns HTTP 200 — a throw
        // here means a real infrastructure problem, not an expired session.
        // If the user truly has no session the server-side requireSession() will
        // have already redirected them before this component even mounts.
        if (!cancelled) {
          setSessionStatus(t("sessionReady"));
        }
      }
    }

    function refreshIfStale() {
      if (document.visibilityState === "visible" && Date.now() - lastSessionCheckAt > SESSION_STALE_MS) {
        void loadSession();
      }
    }

    // Mount: die mitgelieferte Sitzung kommt frisch vom Server und wird sofort angewendet. Beim
    // ersten Mount des Dokuments zusätzlich im Hintergrund aus dem Browser prüfen (Bridge).
    if (initialSession?.authenticated) {
      lastSessionCheckAt = Date.now();
      applySession(initialSession);
      if (!browserSessionChecked) {
        void loadSession();
      }
    } else {
      void loadSession();
    }

    window.addEventListener("focus", refreshIfStale);
    document.addEventListener("visibilitychange", refreshIfStale);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", refreshIfStale);
      document.removeEventListener("visibilitychange", refreshIfStale);
    };
    // Laeuft beim Mount und wenn der Server eine neue Sitzung mitliefert (router.refresh(),
    // Seitenwechsel innerhalb derselben Route) - dann ohne zusaetzlichen Request.
  }, [initialSession, router, t]);

  const activeCrumb = useMemo(() => {
    // Einstellungen: «Einstellungen / <Seite>», die Gruppe verlinkt auf die Übersicht
    if (pathname === SETTINGS_HREF) {
      return { group: null, label: t(SETTINGS_GROUP), settings: false };
    }
    const setting = activeSettingsLink(settingsGroups, pathname);
    if (setting) {
      return { group: t(SETTINGS_GROUP), label: t(setting.labelKey), settings: true };
    }
    for (const group of navGroups) {
      for (const link of group.links) {
        if (isNavLinkActive(link, pathname)) {
          return { group: group.titleKey ? t(group.titleKey) : null, label: t(link.labelKey), settings: false };
        }
      }
    }
    // Seiten aus dem Benutzermenue stehen nicht in der Sidebar-Navigation.
    if (pathname === CONNECTIONS_HREF) {
      return { group: null, label: t("connections"), settings: false };
    }
    return { group: null, label: t("dashboard"), settings: false };
  }, [navGroups, settingsGroups, pathname, t]);

  const related = useMemo(() => relatedNavLink(navGroups, settingsGroups, pathname), [navGroups, settingsGroups, pathname]);

  const tenantName = session?.current_tenant?.name ?? t("defaultTenantName");
  const userInitial = session?.user?.display_name?.slice(0, 1) ?? "U";
  const roleLabel = formatRoleLabel(session, t) || sessionStatus;

  function selectTheme(nextTheme: "light" | "dark" | "auto") {
    setThemePreference(nextTheme);
    window.localStorage.setItem("hocx-theme", nextTheme);
    document.documentElement.dataset.themePreference = nextTheme;
  }

  async function saveProfile() {
    try {
      await browserApiFetch("/api/users/me", {
        method: "PATCH",
        body: JSON.stringify({
          preferred_language: language,
        })
      });
      const refreshed = await browserApiFetch<SessionInfo>("/api/auth/session");
      setSession(refreshed);
      setProfileModalOpen(false);
      router.refresh();
    } catch {
      showToast(tSettings("profileModal.saveFailed"), "error");
    }
  }

  async function logout() {
    // Ungesendete Änderungen gehen beim Abmelden verloren - die Ablage wird geleert, damit auf
    // einem geteilten Gerät kein Protokolltext zurückbleibt (Datenschutz-Audit PRIV-019).
    if (getOfflineSnapshot().pending > 0) {
      const ok = await confirm({ tone: "danger", message: tSettings("logoutPendingConfirm"), confirmLabel: tSettings("logoutAnyway") });
      if (!ok) return;
    }
    try {
      await browserApiFetch("/api/auth/logout", { method: "POST" });
      clearOfflineStore();
      clearSimilarityGroupsCache();
      window.sessionStorage.removeItem("hocx-tenant-prompted");
      redirectToLogin(router);
    } catch {
      showToast(tSettings("logoutFailed"), "error");
    }
  }

  function runSearchAction(action: GlobalSearchAction) {
    if (action === "profile") setProfileModalOpen(true);
    else selectTheme(action === "theme-light" ? "light" : action === "theme-dark" ? "dark" : "auto");
  }

  // Direktlink ?profile=notifications|profile öffnet das Profil im passenden Reiter (Link im Fuss
  // jeder Benachrichtigungs-Mail); der Parameter verschwindet danach aus der Adresse.
  // Ohne Anmeldung führt die Weiterleitung zum Login ohne Parameter zurück: das Ziel bleibt bis
  // dahin im Tab gespeichert (sessionStorage) und öffnet sich, sobald eine Sitzung da ist.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const target = params.get("profile");
    if (target) {
      try { window.sessionStorage.setItem(PROFILE_LINK_KEY, target); } catch { /* ohne Speicher: nur jetzt */ }
      params.delete("profile");
      const query = params.toString();
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
    }
    if (!session) return;
    let pending = target;
    try {
      pending = window.sessionStorage.getItem(PROFILE_LINK_KEY) ?? target;
      window.sessionStorage.removeItem(PROFILE_LINK_KEY);
    } catch { /* ohne Speicher: Wert aus der Adresse */ }
    if (!pending) return;
    setProfileInitialTab(profileTabFromLink(pending));
    setProfileModalOpen(true);
  }, [pathname, session]);

  const globalSearch = searchOpen ? (
    <GlobalSearch open onClose={() => setSearchOpen(false)} session={session} listInput={searchListInput} onAction={runSearchAction} pendingKeys={pendingSearchKeys} />
  ) : null;

  const shortcutHelp = shortcutHelpOpen ? <ShortcutHelp open onClose={() => setShortcutHelpOpen(false)} /> : null;

  const profileModal = profileModalOpen ? (
    <ProfileModal
      open
      initialTab={profileInitialTab}
      onClose={() => { setProfileModalOpen(false); setProfileInitialTab(undefined); }}
      language={language}
      onLanguageChange={setLanguage}
      onSave={saveProfile}
      onLogout={() => void logout()}
    />
  ) : null;

  // Desktop: Rahmen mit Sidebar und Kopfzeile. Mobile (bis 900 px): Tableiste statt Sidebar, nur die
  // Bereiche aus dem Mobile-Design stehen in der Navigation (siehe mobile-shell.tsx). Beide Ansichten
  // teilen sich denselben Baum bis zum Seiteninhalt: nur Navigation und Rahmen wechseln, wo die
  // andere Ansicht kein Element hat, steht eine unsichtbare Hülle (`.shell-slot`, display: contents).
  // So bleiben Eingaben, Dialoge und Fokus beim Drehen des Tablets oder Schmalziehen des Fensters
  // erhalten (1.6; vorher tauschte die Shell den ganzen Baum und mountete die Seite neu). Nur die
  // erste Korrektur nach dem Laden baut neu auf (viewportEpoch), wie vorher.
  const desktop = !isMobile;
  const frameClass = desktop
    ? `app-frame${isProtocolWriting ? " app-frame-writing" : ""}${protocolExitAnimation ? " app-frame-protocol-exit" : ""}`
    : "mobile-shell";

  return (
    <MobileShellProviders session={session} onOpenMore={openMobileMore}>
    {/* Key wechselt nur bei der ersten Korrektur nach dem Laden (Server rendert Desktop, Client
        ist schmal): dann wie bisher neu aufbauen, spaetere Wechsel behalten den Inhalt. */}
    <div key={viewportEpoch} className={frameClass}>
      {desktop ? <SkipLink /> : null}
      <ConnectivityStatus userId={session?.user?.id ?? null} />
      <div className={desktop ? "shell" : "shell-slot"}>
        {desktop && isProtocolWriting && (
          <div
            className="sidebar-edge-trigger"
            aria-hidden="true"
            onMouseEnter={() => setMobileNavOpen(true)}
          />
        )}
        {desktop && mobileNavOpen && (
          <div className="sidebar-overlay" aria-hidden="true" onClick={() => setMobileNavOpen(false)} />
        )}
        {desktop ? (
        <aside
          ref={sidebarRef}
          className={`sidebar${mobileNavOpen ? " sidebar-open" : ""}${isProtocolWriting ? " sidebar-writing" : ""}`}
          onMouseLeave={() => {
            // In protocol writing, the sidebar is a temporary overlay opened from either
            // the left-edge hotspot or the menu button.
            if (isProtocolWriting && mobileNavOpen) {
              setMobileNavOpen(false);
            }
          }}
        >
          <div className="brand-lockup">
            {session?.current_tenant?.profile_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                className="brand-mark brand-mark-tenant"
                src={session.current_tenant.profile_image_url}
                alt={t("tenantLogoAlt", { tenant: tenantName })}
              />
            ) : (
              <div className="brand-mark">hX</div>
            )}
            <div className="brand-lockup-text">
              <div className="sidebar-wordmark">hocX</div>
              <div className="sidebar-tenant-name">{tenantName}</div>
            </div>
          </div>
          <nav className="sidebar-nav">
            {navGroups.map((group) => {
              const renderLink = (link: NavLink) => (
                <Link
                  href={link.href as Route}
                  key={link.href}
                  className={isNavLinkActive(link, pathname) ? "nav-link nav-link-active" : "nav-link"}
                  aria-current={isNavLinkActive(link, pathname) ? "page" : undefined}
                  onClick={() => setMobileNavOpen(false)}
                >
                  <NavIcon name={link.icon} className="nav-link-icon" />
                  <span className="nav-link-label">{t(link.labelKey)}</span>
                </Link>
              );
              if (group.titleKey === null) {
                return (
                  <div className="nav-links" key="ungrouped">
                    {group.links.map(renderLink)}
                  </div>
                );
              }
              const isExpanded = expandedNavGroup === group.titleKey;
              return (
                <div className={`nav-group${isExpanded ? " nav-group-expanded" : ""}`} key={group.titleKey}>
                  <button
                    type="button"
                    className="nav-group-label"
                    aria-expanded={isExpanded}
                    onClick={() => setExpandedNavGroup(group.titleKey)}
                  >
                    <span>{t(group.titleKey)}</span>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" width={14} height={14} aria-hidden="true">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </button>
                  {isExpanded && <div className="nav-links">{group.links.map(renderLink)}</div>}
                </div>
              );
            })}
          </nav>
          <div className="sidebar-footer">
            {settingsGroups.length > 0 ? (
              <Link
                href={SETTINGS_HREF as Route}
                className={inSettings ? "nav-link sidebar-settings-link nav-link-active" : "nav-link sidebar-settings-link"}
                aria-current={inSettings ? "page" : undefined}
                onClick={() => setMobileNavOpen(false)}
              >
                <SettingsIcon className="nav-link-icon" />
                <span className="nav-link-label">{t(SETTINGS_GROUP)}</span>
              </Link>
            ) : null}
            <div className="identity-panel">
              <div className="identity-card">
                <button
                  ref={avatarTriggerRef}
                  type="button"
                  className="identity-button"
                  aria-haspopup="menu"
                  aria-expanded={avatarMenuOpen}
                  onClick={() => setAvatarMenuOpen((current) => !current)}
                  onKeyDown={menuButtonKeyDown(avatarMenuOpen, setAvatarMenuOpen)}
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
        ) : null}
        <div className={desktop ? "shell-main" : "shell-slot"}>
          {desktop ? (
          <header className="topbar">
            <div className="topbar-actions">
              <button
                ref={navToggleRef}
                type="button"
                className="button-ghost mobile-nav-toggle"
                aria-expanded={mobileNavOpen}
                aria-label={mobileNavOpen ? undefined : tCommon("menuToggle")}
                onClick={(event) => {
                  const opening = !mobileNavOpen;
                  setMobileNavOpen(opening);
                  // Per Tastatur geöffnet (detail 0): Fokus in die Leiste, sie steht im DOM vor dem Knopf
                  if (opening && event.detail === 0) {
                    window.requestAnimationFrame(() => sidebarRef.current?.querySelector<HTMLElement>(".nav-link-active, .nav-link")?.focus());
                  }
                }}
              >
                {mobileNavOpen ? t("menuToggleClose") : <span aria-hidden="true">☰</span>}
              </button>
            </div>
            <nav className="topbar-breadcrumb" aria-label={tCommon("breadcrumbNav")}>
              {activeCrumb.group ? (
                <>
                  {activeCrumb.settings ? (
                    <Link href={SETTINGS_HREF as Route} className="topbar-breadcrumb-group topbar-breadcrumb-link">{activeCrumb.group}</Link>
                  ) : (
                    <span className="topbar-breadcrumb-group">{activeCrumb.group}</span>
                  )}
                  <span className="topbar-breadcrumb-sep">/</span>
                </>
              ) : null}
              <span className="topbar-breadcrumb-page">{activeCrumb.label}</span>
            </nav>
            {related?.kind === "settings" && (
              <Link
                href={related.link.href as Route}
                className="topbar-related"
                aria-label={t("related.openSettings", { name: t(related.link.labelKey) })}
              >
                <SettingsIcon className="topbar-related-icon" width={16} height={16} />
                <span className="topbar-related-label">{t(related.link.labelKey)}</span>
              </Link>
            )}
            {related?.kind === "area" && (
              <Link
                href={related.link.href as Route}
                className="topbar-related"
                aria-label={t("related.backToArea", { area: t(related.groupTitleKey) })}
              >
                <span aria-hidden="true">←</span>
                <span className="topbar-related-label">{t("related.backToArea", { area: t(related.groupTitleKey) })}</span>
              </Link>
            )}
            <button type="button" className="global-search-trigger" onClick={openSearch} aria-keyshortcuts="Control+K Meta+K">
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <circle cx="7" cy="7" r="5.25" stroke="currentColor" strokeWidth="1.5" />
                <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <span className="global-search-trigger-label">{tCommon("globalSearch")}</span>
              <kbd className="global-search-kbd">{shortcut("K")}</kbd>
            </button>
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
                  {t("profileEdit")}
                </MenuItem>
                <MenuItem
                  selected={pathname === CONNECTIONS_HREF}
                  onSelect={() => {
                    setAvatarMenuOpen(false);
                    router.push(CONNECTIONS_HREF as Route);
                  }}
                >
                  {t("connections")}
                </MenuItem>
                <MenuItem
                  onSelect={() => {
                    setAvatarMenuOpen(false);
                    setShortcutHelpOpen(true);
                  }}
                >
                  <span className="menu-item-with-kbd">
                    {tCommon("keyboard.helpTitle")}
                    <kbd className="global-search-kbd">?</kbd>
                  </span>
                </MenuItem>
                <MenuDivider />
                <div className="menu-header menu-header-tight">{t("appearance")}</div>
                <MenuItem selected={themeReady && themePreference === "light"} onSelect={() => selectTheme("light")}>
                  {t("themeLight")}
                </MenuItem>
                <MenuItem selected={themeReady && themePreference === "dark"} onSelect={() => selectTheme("dark")}>
                  {t("themeDark")}
                </MenuItem>
                <MenuItem selected={themeReady && themePreference === "auto"} onSelect={() => selectTheme("auto")}>
                  {t("themeAuto")}
                </MenuItem>
                <MenuDivider />
                <MenuItem
                  danger
                  onSelect={() => {
                    setAvatarMenuOpen(false);
                    void logout();
                  }}
                >
                  {t("logout")}
                </MenuItem>
              </Menu>
            </Popover>
          </header>
          ) : null}
          {/* Inhalt bleibt beim Oeffnen von "Mehr" montiert, damit Filter/Scrollposition erhalten bleiben. */}
          <main id={MAIN_CONTENT_ID} tabIndex={-1} className={desktop ? "shell-content" : "mobile-shell-content"} hidden={!desktop && mobileMoreOpen}>
            {desktop ? (
              <PasswordBreachedBanner
                breached={session?.password_breached}
                onChange={() => { setProfileInitialTab(profileTabFromLink("security")); setProfileModalOpen(true); }}
              />
            ) : null}
            {desktop ? <MfaGraceBanner until={session?.mfa_grace_until} onSetup={() => setProfileModalOpen(true)} /> : null}
            <InstallAppPrompt />
            <SettingsFrame groups={settingsGroups} pathname={pathname} enabled={desktop && inSettings && usesSettingsFrame(pathname)}>
              {children}
            </SettingsFrame>
          </main>
        </div>
      </div>
      {!desktop && mobileMoreOpen ? (
        <MobileMorePanel
          session={session}
          themePreference={themePreference}
          themeReady={themeReady}
          onSelectTheme={selectTheme}
          onOpenProfile={() => setProfileModalOpen(true)}
          onOpenSearch={() => { setMobileMoreOpen(false); openSearch(); }}
          onLogout={() => void logout()}
        />
      ) : null}
      {!desktop ? <MobileTabBar session={session} moreOpen={mobileMoreOpen} onMoreOpenChange={setMobileMoreOpen} /> : null}

      {profileModal}
      {globalSearch}
      {shortcutHelp}
    </div>
    </MobileShellProviders>
  );
}
