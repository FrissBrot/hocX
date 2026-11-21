"use client";

import type { Route } from "next";
import { KeyboardEvent, MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { CommandPalette, type PaletteEntry } from "@/components/search/command-palette";
import { NavIcon } from "@/components/ui/nav-icons";
import { browserApiFetch } from "@/lib/api/client";
import { can, roleName } from "@/lib/permissions";
import { storeSearchHandoff } from "@/lib/search/handoff";
import { focusListSearch } from "@/lib/search/list-search";
import { rankEntries } from "@/lib/search/match";
import { crossLanguageKeywords, loadOtherLanguages, type LanguageBundle } from "@/lib/search/multilingual";
import { useShortcutLabel } from "@/lib/search/shortcuts";
import { buildStaticEntries, type SearchEntry, type SearchGroup } from "@/lib/search/static-entries";
import type { GlobalSearchResult, RoleRead, SessionInfo } from "@/types/api";

const REMOTE_DEBOUNCE_MS = 200;
const MIN_REMOTE_LENGTH = 2;
const RECENT_KEY = "hocx-search-recent";
const RECENT_LIMIT = 6;
const GROUP_ORDER: SearchGroup[] = ["list", "recent", "pages", "settings", "roles", "elements", "lists", "people", "files"];

export type GlobalSearchAction = "profile" | "theme-light" | "theme-dark" | "theme-auto";

type RecentEntry = Pick<SearchEntry, "id" | "label" | "sublabel" | "href" | "icon">;

// Zuletzt geöffnet: nur Menüs und Einstellungen (keine Personen- oder Dateinamen auf dem Gerät),
// je Konto. Bequemlichkeit pro Browser - fehlt sie, startet die Suche einfach leer.
function readRecent(userId: string | null): RecentEntry[] {
  if (!userId) return [];
  try {
    const stored = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "null") as { user: string; items: RecentEntry[] } | null;
    return stored && stored.user === userId && Array.isArray(stored.items) ? stored.items.slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

function rememberRecent(userId: string | null, entry: SearchEntry) {
  if (!userId || !entry.href || (entry.group !== "pages" && entry.group !== "settings" && entry.group !== "recent")) return;
  try {
    const items = [
      { id: entry.id, label: entry.label, sublabel: entry.sublabel, href: entry.href, icon: entry.icon },
      ...readRecent(userId).filter((item) => item.id !== entry.id),
    ].slice(0, RECENT_LIMIT);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify({ user: userId, items }));
  } catch {
    // ohne Speicher keine Liste «Zuletzt geöffnet»
  }
}

/**
 * Globale Suche (Ctrl+K / ⌘K, Knopf in der Kopfleiste, mobil unter «Mehr»): Menüs und
 * Einstellungen aus der Navigation (sofort, ohne Server), Personen und Dateien über
 * POST /api/search (Personen, Dateien, Elemente und Listen, je nach Berechtigung). Hat die Seite eine Liste mit
 * Suchfeld, steht «In dieser Liste suchen» zuoberst.
 */
export function GlobalSearch({
  open,
  onClose,
  session,
  listInput,
  onAction,
  pendingKeys,
}: {
  open: boolean;
  onClose: () => void;
  session: SessionInfo | null;
  /** Suchfeld der Liste auf der aktuellen Seite (beim Öffnen ermittelt), sonst null */
  listInput: HTMLInputElement | null;
  onAction: (action: GlobalSearchAction) => void;
  /** Zeichen, die vor dem Montieren getippt wurden (app-shell.tsx) */
  pendingKeys?: MutableRefObject<{ text: string; consumed: boolean }>;
}) {
  const t = useTranslations("search");
  const tNav = useTranslations("nav");
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [remote, setRemote] = useState<GlobalSearchResult | null>(null);
  const [remoteState, setRemoteState] = useState<"idle" | "loading" | "error">("idle");
  const [recent, setRecent] = useState<RecentEntry[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const userId = session?.user?.id != null ? String(session.user.id) : null;
  const searchesPeople = can(session, "participants.read");
  const searchesFiles = can(session, "files.read") || can(session, "photos.read");
  const searchesElements = can(session, "templates.edit");
  const searchesLists = can(session, "meetings.edit");
  const searchesRoles = can(session, "access.manage");
  const [roles, setRoles] = useState<RoleRead[] | null>(null);
  const shortcut = useShortcutLabel();

  const locale = useLocale();
  // Andere Sprachen als zusätzliche Suchbegriffe («settings», «logs» auch auf Deutsch), beim
  // Öffnen nachgeladen (lib/search/multilingual.ts)
  const [otherLanguages, setOtherLanguages] = useState<LanguageBundle[]>([]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    void loadOtherLanguages(locale).then((bundles) => { if (active) setOtherLanguages(bundles); });
    return () => { active = false; };
  }, [open, locale]);
  const staticEntries = useMemo(() => {
    const entries = buildStaticEntries(session, tNav, t);
    if (otherLanguages.length === 0) return entries;
    const extra = crossLanguageKeywords(session, otherLanguages);
    return entries.map((entry) => {
      const words = extra.get(entry.id);
      return words ? { ...entry, keywords: [entry.keywords, words].filter(Boolean).join(" ") } : entry;
    });
  }, [session, tNav, t, otherLanguages]);

  useEffect(() => {
    if (!open) return;
    // Das Fenster wird bei jedem Öffnen neu montiert (Zustand startet leer); die Suche nicht
    // zurücksetzen - sonst gingen die vor dem Montieren getippten Zeichen verloren.
    setRemote(null);
    setRecent(readRecent(userId));
    const raf = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(raf);
  }, [open, userId]);

  // Das Fenster wird bei jedem Öffnen neu geladen und montiert (dynamic import). Der Fokus
  // gehört ins Suchfeld, sobald es existiert - nicht nach einem Frame, in dem es noch fehlen
  // kann (dann setzte der Dialog den Fokus auf sich selbst und Tippen ging ins Leere).
  function focusOnMount(element: HTMLInputElement | null) {
    inputRef.current = element;
    if (!element) return;
    if (document.activeElement !== element) element.focus({ preventScroll: true });
    // Vor dem Montieren getippte Zeichen übernehmen (app-shell sammelt sie)
    const pending = pendingKeys?.current;
    if (pending && !pending.consumed) {
      pending.consumed = true;
      if (pending.text) setQuery(pending.text);
    }
  }

  const trimmed = query.trim();

  // Rollen: einmal je Öffnen laden (wenige Einträge), gesucht wird lokal über den angezeigten
  // Namen - Standardrollen heissen je Sprache anders (name ist dort leer).
  useEffect(() => {
    if (!open || !searchesRoles || roles !== null || !trimmed) return;
    let active = true;
    browserApiFetch<RoleRead[]>("/api/roles")
      .then((loaded) => { if (active) setRoles(loaded ?? []); })
      .catch(() => { if (active) setRoles([]); });
    return () => { active = false; };
  }, [open, searchesRoles, roles, trimmed]);

  // Personen und Dateien: nach einer kurzen Tipppause, veraltete Anfragen werden abgebrochen
  useEffect(() => {
    if (!open || (!searchesPeople && !searchesFiles && !searchesElements && !searchesLists) || trimmed.length < MIN_REMOTE_LENGTH) {
      setRemote(null);
      setRemoteState("idle");
      return;
    }
    const controller = new AbortController();
    setRemoteState("loading");
    const timer = window.setTimeout(() => {
      browserApiFetch<GlobalSearchResult>("/api/search", { method: "POST", body: JSON.stringify({ q: trimmed }), signal: controller.signal })
        .then((result) => { setRemote(result); setRemoteState("idle"); })
        .catch(() => { if (!controller.signal.aborted) { setRemote(null); setRemoteState("error"); } });
    }, REMOTE_DEBOUNCE_MS);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [open, trimmed, searchesPeople, searchesFiles, searchesElements, searchesLists]);

  const entries = useMemo<SearchEntry[]>(() => {
    if (!trimmed) {
      return recent.map((item) => ({ ...item, group: "recent" as const }));
    }
    // Kein Eintrag «In dieser Liste suchen» mehr (Wunsch: Seitenwechsel per Strg+K bleibt ein Enter
    // ohne Pfeiltaste); die Listensuche hat ihr eigenes Kürzel (Hinweis unten im Fuss).
    const result: SearchEntry[] = [];
    const ranked = rankEntries(staticEntries, trimmed, 10);
    result.push(...ranked.filter((entry) => entry.group === "pages"), ...ranked.filter((entry) => entry.group === "settings"));
    const roleEntries: SearchEntry[] = (roles ?? []).map((role) => ({
      id: `role:${role.id}`,
      group: "roles",
      label: roleName(role, tNav),
      sublabel: role.description || t("roleLabel"),
      keywords: role.system_key ?? undefined,
      icon: "users",
      href: `/users/roles?role=${role.id}`,
    }));
    result.push(...rankEntries(roleEntries, trimmed, 5));
    for (const element of remote?.elements ?? []) {
      result.push({
        id: `element:${element.id}`,
        group: "elements",
        label: element.title,
        sublabel: element.description || undefined,
        icon: "elements",
        href: `/elements?open=${element.id}`,
      });
    }
    for (const block of remote?.blocks ?? []) {
      result.push({
        id: `block:${block.element_id}:${block.block_id}`,
        group: "elements",
        label: block.title,
        sublabel: t("blockIn", { element: block.element_title }),
        icon: "elements",
        href: `/elements?open=${block.element_id}&block=${block.block_id}`,
      });
    }
    // Listen nur nach Namen; nicht in «Zuletzt geöffnet» (rememberRecent nimmt nur Menüs/Einstellungen)
    for (const list of remote?.lists ?? []) {
      result.push({
        id: `lists:${list.id}`,
        group: "lists",
        label: list.name,
        sublabel: list.description || undefined,
        icon: "lists",
        href: `/lists?open=${list.id}`,
      });
    }
    for (const person of remote?.people ?? []) {
      result.push({
        id: `person:${person.id}`,
        group: "people",
        label: person.name,
        sublabel: [person.email, person.is_active ? null : t("inactive")].filter(Boolean).join(" · ") || undefined,
        icon: "participants",
        href: `/participants?open=${person.id}`,
      });
    }
    for (const file of remote?.files ?? []) {
      result.push({
        id: `file:${file.id}`,
        group: "files",
        label: file.name,
        sublabel: file.context || undefined,
        keywords: file.name,
        icon: file.is_image ? "photos" : "files",
        href: `${file.is_image ? "/photos" : "/files"}?open=${file.id}`,
      });
    }
    return result.sort((a, b) => GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group));
  }, [trimmed, recent, listInput, staticEntries, remote, t, roles, tNav]);

  function select(entry: SearchEntry) {
    onClose();
    if (entry.action) {
      onAction(entry.action);
      return;
    }
    if (!entry.href) return;
    if (entry.group === "files") storeSearchHandoff({ id: entry.id.slice("file:".length), search: entry.label });
    rememberRecent(userId, entry);
    router.push(entry.href as Route);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>): boolean {
    // Strg+F / ⌘F im Suchfenster: den getippten Begriff in die Listensuche der Seite übernehmen
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "f" && listInput) {
      event.preventDefault();
      onClose();
      focusListSearch(listInput, trimmed);
      return true;
    }
    return false;
  }

  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const paletteEntries: PaletteEntry<SearchGroup>[] = entries.map((entry) => ({
    id: entry.id,
    group: entry.group,
    label: entry.label,
    sublabel: entry.sublabel,
    icon: entry.icon ? <NavIcon name={entry.icon} /> : undefined,
  }));

  return (
    <CommandPalette
      open={open}
      onClose={onClose}
      title={t("title")}
      query={query}
      onQueryChange={setQuery}
      entries={paletteEntries}
      groupLabel={(group) => (group === "list" ? null : t(`groups.${group}`))}
      onSelect={(entry) => { const original = byId.get(entry.id); if (original) select(original); }}
      placeholder={t(searchesPeople || searchesFiles ? "placeholder" : "placeholderMenus")}
      emptyText={!trimmed ? t("emptyStart") : remoteState === "loading" ? t("loading") : t("noResults", { query: trimmed })}
      status={
        <>
          {trimmed && remoteState === "loading" && entries.length > 0 ? <div className="global-search-status">{t("loading")}</div> : null}
          {remoteState === "error" ? <div className="global-search-status" role="status">{t("remoteFailed")}</div> : null}
        </>
      }
      footer={
        <>
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">↑↓</kbd> {t("hintSelect")}</span>
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">↵</kbd> {t("hintOpen")}</span>
          {listInput ? <span className="global-search-footer-hint"><kbd className="global-search-kbd">{shortcut("F")}</kbd> {t("hintList")}</span> : null}
        </>
      }
      onInputKeyDown={handleKeyDown}
      inputRef={focusOnMount}
      idPrefix="global-search"
    />
  );
}
