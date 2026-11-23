"use client";

import Link from "next/link";
import type { Route } from "next";
import dynamic from "next/dynamic";
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";
import { ToastProvider } from "@/contexts/toast-context";
import { ConfirmProvider } from "@/contexts/confirm-context";
import type { AdminSessionInfo } from "@/types/api";
import type { AdminPaletteAction } from "@/components/admin/admin-command-palette";
import { AdminNavIcon } from "@/components/ui/admin-nav-icons";
import {
  ADMIN_NAV_GROUP_KEY,
  activeAdminGroupId,
  adminBreadcrumb,
  attentionItems,
  buildAdminNav,
  groupCount,
  linkCount,
  resolveOpenAdminGroup,
  toggleAdminGroup,
  type AdminNavCounts,
  type AdminNavLink,
} from "@/components/ui/admin-shell-nav";
import { Badge } from "@/components/ui/badge";
import { Menu, MenuDivider, MenuItem, menuButtonKeyDown, Popover } from "@/components/ui/popover";
import { CopyrightNotice } from "@/components/ui/copyright-notice";
import { SkipLink } from "@/components/ui/skip-link";
import { MAIN_CONTENT_ID } from "@/lib/a11y/focus";
import { useFocusRescue } from "@/lib/a11y/use-focus-rescue";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { useGlobalSearchShortcuts, useShortcutLabel } from "@/lib/search/shortcuts";
import { PasswordBreachedBanner } from "@/components/ui/password-breached-banner";

const AdminCommandPalette = dynamic(() => import("@/components/admin/admin-command-palette").then((m) => m.AdminCommandPalette), { ssr: false });
const ShortcutHelp = dynamic(() => import("@/components/ui/shortcut-help").then((m) => m.ShortcutHelp), { ssr: false });

const COMPACT_KEY = "hocx-admin-sidebar";
const COUNTS_INTERVAL_MS = 60_000;

type ThemePreference = "light" | "dark" | "auto";

function readCompact(): boolean {
  try {
    return window.localStorage.getItem(COMPACT_KEY) === "compact";
  } catch {
    return false;
  }
}

/**
 * Rahmen der Admin-Konsole (Plan §6.1): Sidebar mit den Bereichen A–G (alle offen, Kompaktmodus),
 * Kopfleiste mit Brotkrumen, Suche (Ctrl+K), Glocke und Umgebungs-Badge. Wird einmal im Layout
 * app/admin/(console)/layout.tsx gemountet, nicht pro Seite.
 */
export function AdminShell({ children, session, environment = "production" }: { children: ReactNode; session: AdminSessionInfo; environment?: string }) {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <AdminShellInner session={session} environment={environment}>{children}</AdminShellInner>
      </ConfirmProvider>
    </ToastProvider>
  );
}

function AdminShellInner({ children, session, environment }: { children: ReactNode; session: AdminSessionInfo; environment: string }) {
  const t = useTranslations("adminShell");
  const tCommon = useTranslations("common");
  const shortcut = useShortcutLabel();
  const pathname = usePathname();
  const router = useRouter();
  const role = session.admin?.role ?? null;
  const navGroups = useMemo(() => buildAdminNav(role), [role]);
  const breadcrumb = adminBreadcrumb(navGroups, pathname);

  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  useShortcut("global.help", () => setShortcutHelpOpen(true));
  useFocusRescue();

  // Suche (Ctrl+K): Zeichen, die vor dem Montieren des Fensters getippt werden, puffern (wie app-shell.tsx)
  const [searchOpen, setSearchOpen] = useState(false);
  const searchOpenRef = useRef(false);
  useEffect(() => {
    searchOpenRef.current = searchOpen;
  }, [searchOpen]);
  const toggleSearch = useCallback(() => setSearchOpen(!searchOpenRef.current), []);
  useGlobalSearchShortcuts(toggleSearch);
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
  useEffect(() => {
    const preload = () => void import("@/components/admin/admin-command-palette");
    const idle = (window as Window & { requestIdleCallback?: (callback: () => void) => number }).requestIdleCallback;
    if (idle) idle(preload);
    else window.setTimeout(preload, 1500);
  }, []);

  // Kompaktmodus der Sidebar (nur Icons), pro Browser gemerkt
  const [compact, setCompact] = useState(false);
  useEffect(() => setCompact(readCompact()), []);
  const toggleCompact = useCallback(() => {
    setCompact((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(COMPACT_KEY, next ? "compact" : "expanded");
      } catch {
        // ohne Speicher gilt der Zustand nur bis zum Neuladen
      }
      return next;
    });
  }, []);
  useShortcut("admin.toggleSidebar", toggleCompact);

  // Einklappbare Bereiche (wie die Mandanten-Sidebar): aktiver Bereich offen, übrige zu
  // Erster Render (auch auf dem Server): aktiver Bereich offen - kein Aufklappen nach dem Laden
  const [openGroup, setOpenGroup] = useState<string | null>(() => activeAdminGroupId(navGroups, pathname));
  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(ADMIN_NAV_GROUP_KEY);
    } catch {
      // ohne Speicher: nur der aktive Bereich
    }
    setOpenGroup(resolveOpenAdminGroup(navGroups, pathname, stored));
  }, [navGroups, pathname]);
  const toggleGroup = useCallback((groupId: string) => {
    setOpenGroup((current) => {
      const next = toggleAdminGroup(current, groupId);
      try {
        if (next) window.localStorage.setItem(ADMIN_NAV_GROUP_KEY, next);
        else window.localStorage.removeItem(ADMIN_NAV_GROUP_KEY);
      } catch {
        // nur Komfort
      }
      return next;
    });
  }, []);

  // Seit 1.5.2 hat die Sidebar die Abstände der App und scrollt bei grossen Bereichen: aktiven Eintrag
  // nach Navigation oder Aufklappen sichtbar halten (nur innerhalb der Navigation, nicht die Seite).
  const sidebarNavRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const nav = sidebarNavRef.current;
    const active = nav?.querySelector<HTMLElement>(".nav-link-active");
    if (!nav || !active) return;
    const navBox = nav.getBoundingClientRect();
    const box = active.getBoundingClientRect();
    if (box.top < navBox.top) nav.scrollTop -= navBox.top - box.top;
    else if (box.bottom > navBox.bottom) nav.scrollTop += box.bottom - navBox.bottom;
  }, [pathname, openGroup, compact]);

  // Zähler für Sidebar und Glocke: ein Request (GET /api/admin/nav-counts), jede Minute bei sichtbarem Tab
  const [counts, setCounts] = useState<AdminNavCounts | null>(null);
  const loadCounts = useCallback(() => {
    browserApiFetch<AdminNavCounts>("/api/admin/nav-counts")
      .then(setCounts)
      .catch(() => setCounts(null));
  }, []);
  useEffect(() => loadCounts(), [loadCounts]);
  useVisibleInterval(loadCounts, COUNTS_INTERVAL_MS);
  const attention = attentionItems(counts, role);
  const attentionTotal = attention.reduce((sum, item) => sum + item.count, 0);

  const avatarTriggerRef = useRef<HTMLButtonElement>(null);
  const bellRef = useRef<HTMLButtonElement>(null);
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const isReadOnlyAdmin = role === "support";
  const isProduction = environment === "production";

  function selectTheme(next: ThemePreference) {
    try {
      window.localStorage.setItem("hocx-theme", next);
    } catch {
      // Darstellung gilt dann nur für diese Seite
    }
    document.documentElement.dataset.themePreference = next;
  }

  async function logout() {
    await browserApiFetch("/api/admin/auth/logout", { method: "POST" });
    router.replace("/admin/login");
  }

  function runPaletteAction(action: AdminPaletteAction) {
    if (action === "shortcuts") setShortcutHelpOpen(true);
    else if (action === "logout") void logout();
    else selectTheme(action === "theme-light" ? "light" : action === "theme-dark" ? "dark" : "auto");
  }

  const renderLink = (link: AdminNavLink) => {
    const active = breadcrumb.link?.href === link.href || (link.href === "/admin" && pathname === "/admin");
    const count = linkCount(link, counts);
    const label = t(link.labelKey);
    return (
      <Link
        href={link.href as Route}
        key={link.href}
        className={active ? "nav-link nav-link-active" : "nav-link"}
        aria-current={active ? "page" : undefined}
        aria-label={compact ? (count !== null ? t("navWithCount", { label, count }) : label) : undefined}
        title={compact ? label : undefined}
        onClick={() => setMobileNavOpen(false)}
      >
        <AdminNavIcon name={link.icon} />
        <span className="nav-link-label">{label}</span>
        {count !== null ? <span className="admin-nav-count">{count}</span> : null}
      </Link>
    );
  };

  const searchTrigger = (extraClass: string) => (
    <button type="button" className={`global-search-trigger ${extraClass}`} onClick={() => setSearchOpen(true)} aria-keyshortcuts="Control+K Meta+K" aria-label={compact && extraClass === "admin-sidebar-search" ? t("search.title") : undefined}>
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="7" cy="7" r="5.25" stroke="currentColor" strokeWidth="1.5" />
        <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span className="global-search-trigger-label">{tCommon("globalSearch")}</span>
      <kbd className="global-search-kbd">{shortcut("K")}</kbd>
    </button>
  );

  return (
    <>
    <div className={compact ? "app-frame admin-frame admin-frame-compact" : "app-frame admin-frame"}>
      <SkipLink />
      <div className="shell">
        {mobileNavOpen && <div className="sidebar-overlay" aria-hidden="true" onClick={() => setMobileNavOpen(false)} />}
        <aside className={mobileNavOpen ? "sidebar admin-sidebar sidebar-open" : "sidebar admin-sidebar"}>
          <div className="brand-lockup">
            <div className="brand-mark">hX</div>
            <div className="admin-brand-copy">
              <div className="eyebrow">hocX</div>
              <h2 className="sidebar-title">{t("title")}</h2>
            </div>
          </div>
          {/* Suche steht in der Kopfleiste (Ctrl+K); in der Sidebar nicht doppelt, damit die Bereiche ohne Scrollen Platz haben (1.5.1) */}
          <nav ref={sidebarNavRef} className="sidebar-nav admin-sidebar-nav" aria-label={t("mainNav")}>
            {navGroups.map((group) => {
              const count = groupCount(group, counts);
              if (!group.titleKey) {
                return (
                  <div className="admin-nav-group" key={group.id}>
                    <div className="nav-links">{group.links.map(renderLink)}</div>
                  </div>
                );
              }
              // Kompaktmodus (nur Icons): alle Bereiche offen, die Köpfe sind dort nur Trennlinien
              const expanded = compact || openGroup === group.id;
              const listId = `admin-nav-group-${group.id}`;
              return (
                <div className={`nav-group admin-nav-group${expanded ? " nav-group-expanded" : ""}`} key={group.id}>
                  {compact ? (
                    <div className="admin-nav-group-title">
                      <span className="admin-nav-group-label">{t(group.titleKey)}</span>
                      {count !== null ? <span className="admin-nav-count admin-nav-count-alert">{count}</span> : null}
                    </div>
                  ) : (
                  <button
                    type="button"
                    className="nav-group-label admin-nav-group-title"
                    aria-expanded={expanded}
                    aria-controls={listId}
                    onClick={() => toggleGroup(group.id)}
                  >
                    <span className="admin-nav-group-label">{t(group.titleKey)}</span>
                    {count !== null ? <span className="admin-nav-count admin-nav-count-alert">{count}</span> : null}
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" width={14} height={14} aria-hidden="true">
                      <path d="M9 18l6-6-6-6" />
                    </svg>
                  </button>
                  )}
                  <div className="nav-links" id={listId} hidden={!expanded}>
                    {group.links.map(renderLink)}
                  </div>
                </div>
              );
            })}
          </nav>
          <div className="sidebar-footer">
            <div className="admin-sidebar-footer-row">
            <div className="admin-identity">
              <button ref={avatarTriggerRef} type="button" className="identity-button admin-identity-trigger" aria-label={t("accountMenu")} aria-haspopup="menu" aria-expanded={avatarMenuOpen} onClick={() => setAvatarMenuOpen((current) => !current)} onKeyDown={menuButtonKeyDown(avatarMenuOpen, setAvatarMenuOpen)}>
                <span className="identity-avatar admin-identity-avatar">{session.admin?.display_name?.slice(0, 1) ?? "A"}</span>
              </button>
              <div className="admin-identity-copy">
                <strong>{session.admin?.display_name ?? "..."}</strong>
                <div className="identity-subtle">{role ? t(`roles.${role}`) : null}</div>
              </div>
            </div>
            <button type="button" className="button-icon admin-compact-toggle" onClick={toggleCompact} aria-pressed={compact} aria-label={compact ? t("expandSidebar") : t("compactSidebar")} title={compact ? t("expandSidebar") : t("compactSidebar")}>
              <span aria-hidden="true">{compact ? "»" : "«"}</span>
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
              aria-expanded={mobileNavOpen}
              aria-label={mobileNavOpen ? undefined : tCommon("menuToggle")}
              onClick={() => setMobileNavOpen((current) => !current)}
            >
              {mobileNavOpen ? t("menuToggleClose") : <span aria-hidden="true">☰</span>}
            </button>
            <nav className="topbar-breadcrumb admin-breadcrumb" aria-label={t("breadcrumbNav")}>
              {breadcrumb.link ? (
                <>
                  {breadcrumb.groupTitleKey && t(breadcrumb.groupTitleKey) !== t(breadcrumb.link.labelKey) ? (
                    <>
                      <span className="topbar-breadcrumb-group">{t(breadcrumb.groupTitleKey)}</span>
                      <span className="topbar-breadcrumb-sep" aria-hidden="true">/</span>
                    </>
                  ) : null}
                  {breadcrumb.nested ? (
                    <>
                      <Link href={breadcrumb.link.href as Route} className="topbar-breadcrumb-group">{t(breadcrumb.link.labelKey)}</Link>
                      <span className="topbar-breadcrumb-sep" aria-hidden="true">/</span>
                      <span aria-current="page">{t("detail")}</span>
                    </>
                  ) : (
                    <span aria-current="page">{t(breadcrumb.link.labelKey)}</span>
                  )}
                </>
              ) : (
                <span aria-current="page">{t("nav.dashboard")}</span>
              )}
            </nav>
            <div className="admin-topbar-actions">
              {searchTrigger("admin-topbar-search")}
              <button
                ref={bellRef}
                type="button"
                className="button-icon admin-bell"
                aria-label={t("attention.label", { count: attentionTotal })}
                aria-haspopup="dialog"
                aria-expanded={bellOpen}
                onClick={() => setBellOpen((current) => !current)}
              >
                <AdminNavIcon name="notifications" />
                {attentionTotal > 0 ? <span className="admin-bell-count" aria-hidden="true">{attentionTotal}</span> : null}
              </button>
              {!isProduction ? (
                <span className="admin-env-badge">
                  <Badge variant={environment === "test" ? "warning" : "info"} dot>{t(`environments.${environment === "test" ? "test" : "development"}`)}</Badge>
                </span>
              ) : null}
            </div>
          </header>
          {isReadOnlyAdmin && <div className="admin-readonly-banner">{t("readOnlyBanner")}</div>}
          <main id={MAIN_CONTENT_ID} tabIndex={-1} className="shell-content">
            <PasswordBreachedBanner breached={session.password_breached} />
            {children}
          </main>
        </div>
      </div>
      {shortcutHelpOpen ? <ShortcutHelp open onClose={() => setShortcutHelpOpen(false)} /> : null}
      {searchOpen ? (
        <AdminCommandPalette open onClose={() => setSearchOpen(false)} navGroups={navGroups} adminId={session.admin?.id ?? null} onAction={runPaletteAction} pendingKeys={pendingSearchKeys} />
      ) : null}
    </div>
    <Popover open={bellOpen} onOpenChange={setBellOpen} anchorRef={bellRef} align="end">
      <div className="admin-attention" role="dialog" aria-label={t("attention.title")}>
        <div className="admin-attention-title">{t("attention.title")}</div>
        {attention.length === 0 ? (
          <p className="muted admin-attention-empty">{t("attention.empty")}</p>
        ) : (
          <ul className="admin-attention-list">
            {attention.map((item) => (
              <li key={item.key}>
                <Link href={item.href as Route} className="admin-attention-item" onClick={() => setBellOpen(false)}>
                  <span>{t(`attention.items.${item.key}`, { count: item.count })}</span>
                  <span aria-hidden="true">→</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Popover>
    <Popover open={avatarMenuOpen} onOpenChange={setAvatarMenuOpen} anchorRef={avatarTriggerRef} align="start">
      <Menu>
        <div className="menu-header">
          <div className="menu-header-name">{session.admin?.display_name}</div>
          <div className="menu-header-role">{session.admin?.email}</div>
        </div>
        <MenuDivider />
        <MenuItem onSelect={() => { setAvatarMenuOpen(false); setMobileNavOpen(false); router.push("/admin/account"); }}>{t("accountSettings")}</MenuItem>
        <MenuItem onSelect={() => { setAvatarMenuOpen(false); selectTheme("light"); }}>{t("actions.themeLight")}</MenuItem>
        <MenuItem onSelect={() => { setAvatarMenuOpen(false); selectTheme("dark"); }}>{t("actions.themeDark")}</MenuItem>
        <MenuItem onSelect={() => { setAvatarMenuOpen(false); selectTheme("auto"); }}>{t("actions.themeAuto")}</MenuItem>
        <MenuItem onSelect={() => { setAvatarMenuOpen(false); setShortcutHelpOpen(true); }}>{t("actions.shortcuts")}</MenuItem>
        <MenuDivider />
        <MenuItem onSelect={() => { setAvatarMenuOpen(false); void logout(); }}>{t("logout")}</MenuItem>
      </Menu>
    </Popover>
    </>
  );
}
