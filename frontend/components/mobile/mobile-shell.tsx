"use client";

import Link from "next/link";
import type { Route } from "next";
import { createContext, CSSProperties, ReactNode, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { MobileIcon, MobileIconName } from "@/components/mobile/mobile-icons";
import { isTodoOverdue } from "@/components/mobile/mobile-utils";
import { MobileAvatar, MobileListRow } from "@/components/mobile/mobile-ui";
import { formatRoleLabel } from "@/components/ui/app-shell-nav";
import { ConnectivityStatus } from "@/components/ui/connectivity-status";
import { browserApiFetch } from "@/lib/api/client";
import type { SessionInfo, TodoListItem } from "@/types/api";

type ThemePreference = "light" | "dark" | "auto";

const MobileSessionContext = createContext<SessionInfo | null>(null);

/** Aktuelle Session fuer Mobile-Ansichten (Benutzer-ID fuer "Meine", Rolle fuer Schreibrechte). */
export function useMobileSession(): SessionInfo | null {
  return useContext(MobileSessionContext);
}

type TabKey = "overview" | "events" | "todos" | "more";

type Tab = { key: TabKey; href: string | null; icon: MobileIconName; labelKey: string };

// Nur die Bereiche aus dem Mobile-Design. Alle anderen Seiten bleiben per Link erreichbar,
// tauchen in der mobilen Navigation aber bewusst nicht auf (nicht fuers Handy optimiert).
function buildTabs(session: SessionInfo | null): Tab[] {
  const role = session?.current_role ?? null;
  const isWriter = role === "admin" || role === "writer";
  return [
    { key: "overview", href: "/", icon: "overview", labelKey: "tabs.overview" },
    ...(isWriter ? [{ key: "events" as const, href: "/events", icon: "calendar" as const, labelKey: "tabs.events" }] : []),
    { key: "todos", href: "/todos", icon: "todos", labelKey: "tabs.todos" },
    { key: "more", href: null, icon: "menu", labelKey: "tabs.more" },
  ];
}

function activeTabFor(pathname: string): TabKey | null {
  if (pathname === "/" || pathname.startsWith("/statistics")) return "overview";
  if (pathname === "/events" || pathname.startsWith("/events/")) return "events";
  if (pathname === "/todos" || pathname.startsWith("/todos/")) return "todos";
  return null;
}

export function MobileShell({
  session,
  children,
  themePreference,
  themeReady,
  onSelectTheme,
  onOpenProfile,
  onLogout,
}: {
  session: SessionInfo | null;
  children: ReactNode;
  themePreference: ThemePreference;
  themeReady: boolean;
  onSelectTheme: (theme: ThemePreference) => void;
  onOpenProfile: () => void;
  onLogout: () => void;
}) {
  const t = useTranslations("mobile");
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const [overdueCount, setOverdueCount] = useState(0);
  const tabs = buildTabs(session);
  const activeTab: TabKey | null = moreOpen ? "more" : activeTabFor(pathname);

  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  // Badge am Todos-Tab: eigene ueberfaellige Todos. Best effort - ohne Antwort bleibt der
  // Tab einfach ohne Zahl, ein Fehler hier darf die Navigation nie blockieren.
  useEffect(() => {
    let cancelled = false;
    browserApiFetch<TodoListItem[]>("/api/todos/my?limit=500")
      .then((todos) => {
        if (!cancelled) setOverdueCount((todos ?? []).filter(isTodoOverdue).length);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  return (
    <MobileSessionContext.Provider value={session}>
      <div className="mobile-shell">
        <ConnectivityStatus />
        {/* Inhalt bleibt beim Oeffnen von "Mehr" montiert, damit Filter/Scrollposition erhalten bleiben. */}
        <div className="mobile-shell-content" hidden={moreOpen}>
          {children}
        </div>
        {moreOpen ? (
          <MobileMorePanel
            session={session}
            themePreference={themePreference}
            themeReady={themeReady}
            onSelectTheme={onSelectTheme}
            onOpenProfile={onOpenProfile}
            onLogout={onLogout}
          />
        ) : null}
        <nav className="mobile-tabbar" aria-label={t("tabs.ariaLabel")} style={{ "--mobile-tabs": tabs.length } as CSSProperties}>
          {tabs.map((tab) => {
            const active = activeTab === tab.key;
            const badge = tab.key === "todos" && overdueCount > 0 ? overdueCount : null;
            const inner = (
              <>
                <span className="mobile-tab-icon">
                  <MobileIcon name={tab.icon} size={24} strokeWidth={1.9} />
                  {badge ? (
                    <span className="mobile-tab-badge" aria-label={t("tabs.overdueBadge", { count: badge })}>
                      {badge}
                    </span>
                  ) : null}
                </span>
                <span className="mobile-tab-label">{t(tab.labelKey)}</span>
              </>
            );
            const className = `mobile-tab${active ? " mobile-tab-active" : ""}`;
            return tab.href ? (
              <Link
                key={tab.key}
                href={tab.href as Route}
                className={className}
                aria-current={active ? "page" : undefined}
                onClick={() => setMoreOpen(false)}
              >
                {inner}
              </Link>
            ) : (
              <button key={tab.key} type="button" className={className} aria-pressed={active} onClick={() => setMoreOpen((open) => !open)}>
                {inner}
              </button>
            );
          })}
        </nav>
      </div>
    </MobileSessionContext.Provider>
  );
}

function MobileMorePanel({
  session,
  themePreference,
  themeReady,
  onSelectTheme,
  onOpenProfile,
  onLogout,
}: {
  session: SessionInfo | null;
  themePreference: ThemePreference;
  themeReady: boolean;
  onSelectTheme: (theme: ThemePreference) => void;
  onOpenProfile: () => void;
  onLogout: () => void;
}) {
  const t = useTranslations("mobile");
  const tNav = useTranslations("nav");
  const name = session?.user?.display_name ?? "…";
  const subtitle = [session?.current_tenant?.name, formatRoleLabel(session?.current_role, tNav)].filter(Boolean).join(" · ");
  const themes: [ThemePreference, string][] = [
    ["light", tNav("themeLight")],
    ["dark", tNav("themeDark")],
    ["auto", tNav("themeAuto")],
  ];

  return (
    <div className="mobile-page mobile-more">
      <h1 className="mobile-page-title mobile-more-title">{t("tabs.more")}</h1>
      <div className="mobile-card mobile-more-profile">
        <MobileAvatar name={name} size="lg" />
        <div className="mobile-more-profile-text">
          <div className="mobile-more-profile-name">{name}</div>
          <div className="mobile-muted-sm">{subtitle}</div>
        </div>
      </div>

      <MobileGroup label={tNav("appearance")}>
        {themes.map(([value, label]) => (
          <MobileListRow
            key={value}
            label={label}
            onClick={() => onSelectTheme(value)}
            chevron={false}
            trailing={themeReady && themePreference === value ? <MobileIcon name="check" className="mobile-list-row-check" /> : null}
          />
        ))}
      </MobileGroup>

      <MobileGroup label={t("more.account")}>
        <MobileListRow label={tNav("profileEdit")} onClick={onOpenProfile} />
        <button type="button" className="mobile-list-row mobile-list-row-danger" onClick={onLogout}>
          <span className="mobile-list-row-label">{tNav("logout")}</span>
        </button>
      </MobileGroup>

      <p className="mobile-more-hint">{t("more.desktopHint")}</p>
    </div>
  );
}

export function MobileGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mobile-group">
      <div className="mobile-group-label">{label}</div>
      <div className="mobile-card mobile-group-card">{children}</div>
    </div>
  );
}
