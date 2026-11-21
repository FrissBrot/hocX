"use client";

import type { Route } from "next";
import { MutableRefObject, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { CommandPalette, type PaletteEntry } from "@/components/search/command-palette";
import { AdminNavIcon } from "@/components/ui/admin-nav-icons";
import { ADMIN_EXTRA_LINKS, type AdminIconKey, type AdminNavGroup } from "@/components/ui/admin-shell-nav";
import { browserApiFetch } from "@/lib/api/client";
import { rankEntries } from "@/lib/search/match";
import { useShortcutLabel } from "@/lib/search/shortcuts";

export type AdminPaletteGroup = "recent" | "pages" | "actions" | "tenants" | "users" | "domains" | "jobs" | "checks" | "audit";
export type AdminPaletteAction = "theme-light" | "theme-dark" | "theme-auto" | "shortcuts" | "logout";

/** Antwort von POST /api/admin/search */
export type AdminSearchItem = { id: string; label: string; sublabel: string | null; href: string };
export type AdminSearchGroup = Exclude<AdminPaletteGroup, "recent" | "pages" | "actions">;
export type AdminSearchResult = { groups: { group: AdminSearchGroup; items: AdminSearchItem[] }[] };

type Entry = PaletteEntry<AdminPaletteGroup> & { href?: string; action?: AdminPaletteAction; keywords?: string; iconKey?: AdminIconKey };

const GROUP_ORDER: AdminPaletteGroup[] = ["recent", "pages", "actions", "tenants", "users", "domains", "jobs", "checks", "audit"];
const REMOTE_DEBOUNCE_MS = 200;
const MIN_REMOTE_LENGTH = 2;
const RECENT_KEY = "hocx-admin-search-recent";
const RECENT_LIMIT = 6;

type RecentEntry = { id: string; label: string; href: string; iconKey?: AdminIconKey };

// Zuletzt geöffnet: nur Seiten (keine Mandanten-, Personen- oder Domainnamen auf dem Gerät), je Admin.
function readRecent(adminId: string | null): RecentEntry[] {
  if (!adminId) return [];
  try {
    const stored = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "null") as { admin: string; items: RecentEntry[] } | null;
    return stored && stored.admin === adminId && Array.isArray(stored.items) ? stored.items.slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

function rememberRecent(adminId: string | null, entry: Entry) {
  if (!adminId || !entry.href || (entry.group !== "pages" && entry.group !== "recent")) return;
  try {
    const items = [
      { id: entry.id, label: entry.label, href: entry.href, iconKey: entry.iconKey },
      ...readRecent(adminId).filter((item) => item.id !== entry.id),
    ].slice(0, RECENT_LIMIT);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify({ admin: adminId, items }));
  } catch {
    // ohne Speicher keine Liste «Zuletzt geöffnet»
  }
}

/**
 * Ctrl+K / ⌘K im Plattform-Admin (Plan §4): Seiten aus der Navigation und Aktionen sofort im
 * Browser, Mandanten/Domains (und für owner Benutzer, Jobs, Checks, Audit) über
 * POST /api/admin/search - der Begriff steht im Body, nie in der URL. Die Palette führt nie selbst
 * etwas Destruktives aus: Treffer navigieren, Aktionen sind Darstellung, Hilfe und Abmelden.
 */
export function AdminCommandPalette({
  open,
  onClose,
  navGroups,
  adminId,
  onAction,
  pendingKeys,
}: {
  open: boolean;
  onClose: () => void;
  navGroups: AdminNavGroup[];
  adminId: string | null;
  onAction: (action: AdminPaletteAction) => void;
  pendingKeys?: MutableRefObject<{ text: string; consumed: boolean }>;
}) {
  const t = useTranslations("adminShell");
  const router = useRouter();
  const shortcut = useShortcutLabel();
  const [query, setQuery] = useState("");
  const [remote, setRemote] = useState<AdminSearchResult | null>(null);
  const [remoteState, setRemoteState] = useState<"idle" | "loading" | "error">("idle");
  const [recent, setRecent] = useState<RecentEntry[]>([]);
  const trimmed = query.trim();

  useEffect(() => {
    if (open) setRecent(readRecent(adminId));
  }, [open, adminId]);

  function focusOnMount(element: HTMLInputElement | null) {
    if (!element) return;
    if (document.activeElement !== element) element.focus({ preventScroll: true });
    const pending = pendingKeys?.current;
    if (pending && !pending.consumed) {
      pending.consumed = true;
      if (pending.text) setQuery(pending.text);
    }
  }

  const staticEntries = useMemo<Entry[]>(() => {
    const pages: Entry[] = [];
    for (const group of navGroups) {
      for (const link of group.links) {
        pages.push({
          id: `page:${link.href}`,
          group: "pages",
          label: t(link.labelKey),
          sublabel: group.titleKey ? t(group.titleKey) : undefined,
          keywords: link.keywordsKey ? t(link.keywordsKey) : undefined,
          href: link.href,
          iconKey: link.icon,
        });
      }
    }
    for (const link of ADMIN_EXTRA_LINKS) {
      pages.push({ id: `page:${link.href}`, group: "pages", label: t(link.labelKey), keywords: link.keywordsKey ? t(link.keywordsKey) : undefined, href: link.href, iconKey: link.icon });
    }
    const actions: Entry[] = [
      { id: "action:theme-light", group: "actions", label: t("actions.themeLight"), keywords: t("keywords.theme"), action: "theme-light" },
      { id: "action:theme-dark", group: "actions", label: t("actions.themeDark"), keywords: t("keywords.theme"), action: "theme-dark" },
      { id: "action:theme-auto", group: "actions", label: t("actions.themeAuto"), keywords: t("keywords.theme"), action: "theme-auto" },
      { id: "action:shortcuts", group: "actions", label: t("actions.shortcuts"), action: "shortcuts" },
      { id: "action:logout", group: "actions", label: t("logout"), action: "logout" },
    ];
    return [...pages, ...actions];
  }, [navGroups, t]);

  useEffect(() => {
    if (!open || trimmed.length < MIN_REMOTE_LENGTH) {
      setRemote(null);
      setRemoteState("idle");
      return;
    }
    const controller = new AbortController();
    setRemoteState("loading");
    const timer = window.setTimeout(() => {
      browserApiFetch<AdminSearchResult>("/api/admin/search", { method: "POST", body: JSON.stringify({ q: trimmed }), signal: controller.signal })
        .then((result) => { setRemote(result); setRemoteState("idle"); })
        .catch(() => { if (!controller.signal.aborted) { setRemote(null); setRemoteState("error"); } });
    }, REMOTE_DEBOUNCE_MS);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, trimmed]);

  const entries = useMemo<Entry[]>(() => {
    if (!trimmed) return recent.map((item) => ({ id: item.id, group: "recent", label: item.label, href: item.href, iconKey: item.iconKey }));
    const result: Entry[] = rankEntries(staticEntries, trimmed, 10);
    for (const group of remote?.groups ?? []) {
      for (const item of group.items.slice(0, 5)) {
        result.push({ id: `${group.group}:${item.id}`, group: group.group, label: item.label, sublabel: item.sublabel ?? undefined, href: item.href });
      }
    }
    return result.sort((a, b) => GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group));
  }, [trimmed, recent, staticEntries, remote]);

  const byId = useMemo(() => new Map(entries.map((entry) => [entry.id, entry])), [entries]);
  const paletteEntries = entries.map((entry) => ({ ...entry, icon: entry.iconKey ? <AdminNavIcon name={entry.iconKey} /> : undefined }));

  function select(entry: PaletteEntry<AdminPaletteGroup>) {
    const original = byId.get(entry.id);
    if (!original) return;
    onClose();
    if (original.action) {
      onAction(original.action);
      return;
    }
    if (!original.href) return;
    rememberRecent(adminId, original);
    router.push(original.href as Route);
  }

  return (
    <CommandPalette
      open={open}
      onClose={onClose}
      title={t("search.title")}
      query={query}
      onQueryChange={setQuery}
      entries={paletteEntries}
      groupLabel={(group) => t(`search.groups.${group}`)}
      onSelect={select}
      placeholder={t("search.placeholder")}
      emptyText={!trimmed ? t("search.emptyStart") : remoteState === "loading" ? t("search.loading") : t("search.noResults", { query: trimmed })}
      status={
        <>
          {trimmed && remoteState === "loading" && entries.length > 0 ? <div className="global-search-status">{t("search.loading")}</div> : null}
          {remoteState === "error" ? <div className="global-search-status" role="status">{t("search.remoteFailed")}</div> : null}
        </>
      }
      footer={
        <>
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">↑↓</kbd> {t("search.hintSelect")}</span>
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">↵</kbd> {t("search.hintOpen")}</span>
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">{shortcut("K")}</kbd> {t("search.hintToggle")}</span>
        </>
      }
      inputRef={focusOnMount}
      idPrefix="admin-search"
    />
  );
}
