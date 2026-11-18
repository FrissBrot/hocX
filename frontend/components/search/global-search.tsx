"use client";

import type { Route } from "next";
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { NavIcon } from "@/components/ui/nav-icons";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { can } from "@/lib/permissions";
import { storeSearchHandoff } from "@/lib/search/handoff";
import { focusListSearch } from "@/lib/search/list-search";
import { rankEntries } from "@/lib/search/match";
import { useShortcutLabel } from "@/lib/search/shortcuts";
import { buildStaticEntries, type SearchEntry, type SearchGroup } from "@/lib/search/static-entries";
import type { GlobalSearchResult, SessionInfo } from "@/types/api";

const REMOTE_DEBOUNCE_MS = 200;
const MIN_REMOTE_LENGTH = 2;
const RECENT_KEY = "hocx-search-recent";
const RECENT_LIMIT = 6;
const GROUP_ORDER: SearchGroup[] = ["list", "recent", "pages", "settings", "people", "files"];

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
 * GET /api/search (nur mit participants.manage bzw. files.manage). Hat die Seite eine Liste mit
 * Suchfeld, steht «In dieser Liste suchen» zuoberst.
 */
export function GlobalSearch({
  open,
  onClose,
  session,
  listInput,
  onAction,
}: {
  open: boolean;
  onClose: () => void;
  session: SessionInfo | null;
  /** Suchfeld der Liste auf der aktuellen Seite (beim Öffnen ermittelt), sonst null */
  listInput: HTMLInputElement | null;
  onAction: (action: GlobalSearchAction) => void;
}) {
  const t = useTranslations("search");
  const tNav = useTranslations("nav");
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [remote, setRemote] = useState<GlobalSearchResult | null>(null);
  const [remoteState, setRemoteState] = useState<"idle" | "loading" | "error">("idle");
  const [recent, setRecent] = useState<RecentEntry[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const userId = session?.user?.id != null ? String(session.user.id) : null;
  const searchesPeople = can(session, "participants.manage");
  const searchesFiles = can(session, "files.manage");
  const shortcut = useShortcutLabel();

  const staticEntries = useMemo(() => buildStaticEntries(session, tNav, t), [session, tNav, t]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    setRemote(null);
    setRecent(readRecent(userId));
    const raf = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(raf);
  }, [open, userId]);

  const trimmed = query.trim();

  // Personen und Dateien: nach einer kurzen Tipppause, veraltete Anfragen werden abgebrochen
  useEffect(() => {
    if (!open || (!searchesPeople && !searchesFiles) || trimmed.length < MIN_REMOTE_LENGTH) {
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
  }, [open, trimmed, searchesPeople, searchesFiles]);

  const entries = useMemo<SearchEntry[]>(() => {
    if (!trimmed) {
      return recent.map((item) => ({ ...item, group: "recent" as const }));
    }
    const result: SearchEntry[] = [];
    if (listInput) {
      result.push({ id: "list", group: "list", label: t("inList", { query: trimmed }), action: "list" });
    }
    const ranked = rankEntries(staticEntries, trimmed, 10);
    result.push(...ranked.filter((entry) => entry.group === "pages"), ...ranked.filter((entry) => entry.group === "settings"));
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
  }, [trimmed, recent, listInput, staticEntries, remote, t]);

  useEffect(() => {
    setActiveIndex(0);
  }, [trimmed]);

  useEffect(() => {
    itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, entries.length]);

  function select(entry: SearchEntry) {
    onClose();
    if (entry.action === "list") {
      if (listInput) focusListSearch(listInput, trimmed);
      return;
    }
    if (entry.action) {
      onAction(entry.action);
      return;
    }
    if (!entry.href) return;
    if (entry.group === "files") storeSearchHandoff({ id: entry.id.slice("file:".length), search: entry.label });
    rememberRecent(userId, entry);
    router.push(entry.href as Route);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => Math.min(entries.length - 1, current + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(0, current - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const entry = entries[activeIndex];
      if (entry) select(entry);
    }
  }

  const activeId = entries[activeIndex] ? `global-search-option-${activeIndex}` : undefined;
  let lastGroup: SearchGroup | null = null;

  return (
    <Modal open={open} onClose={onClose} title={t("title")} hideHeader className="global-search-shell">
      <div className="global-search" data-global-search>
        <div className="global-search-field-row">
          <SearchInput
            ref={inputRef}
            value={query}
            onChange={setQuery}
            onKeyDown={handleKeyDown}
            placeholder={t(searchesPeople || searchesFiles ? "placeholder" : "placeholderMenus")}
            className="global-search-input"
            aria-label={t("title")}
            role="combobox"
            aria-expanded
            aria-controls="global-search-results"
            aria-activedescendant={activeId}
            aria-autocomplete="list"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="global-search-kbd">Esc</kbd>{/* i18n-ok: Tastenname, sprachunabhaengig */}
        </div>

        <div className="global-search-list" id="global-search-results" role="listbox" aria-label={t("results")}>
          {entries.length === 0 ? (
            <div className="global-search-empty">
              {!trimmed
                ? t("emptyStart")
                : remoteState === "loading"
                  ? t("loading")
                  : t("noResults", { query: trimmed })}
            </div>
          ) : (
            entries.map((entry, index) => {
              const heading = entry.group !== lastGroup && entry.group !== "list" ? <div className="global-search-group" role="presentation">{t(`groups.${entry.group}`)}</div> : null;
              lastGroup = entry.group;
              const active = index === activeIndex;
              return (
                <div key={entry.id} role="presentation">
                  {heading}
                  <button
                    id={`global-search-option-${index}`}
                    type="button"
                    role="option"
                    aria-selected={active}
                    tabIndex={-1}
                    ref={(node) => { itemRefs.current[index] = node; }}
                    className={`global-search-item${active ? " global-search-item-active" : ""}`}
                    onMouseMove={() => { if (index !== activeIndex) setActiveIndex(index); }}
                    onClick={() => select(entry)}
                  >
                    <span className="global-search-item-icon" aria-hidden="true">
                      {entry.icon ? <NavIcon name={entry.icon} /> : <span className="global-search-item-dot" />}
                    </span>
                    <span className="global-search-item-text">
                      <span className="global-search-item-title">{entry.label}</span>
                      {entry.sublabel ? <span className="global-search-item-sub">{entry.sublabel}</span> : null}
                    </span>
                  </button>
                </div>
              );
            })
          )}
          {trimmed && remoteState === "loading" && entries.length > 0 ? <div className="global-search-status">{t("loading")}</div> : null}
          {remoteState === "error" ? <div className="global-search-status" role="status">{t("remoteFailed")}</div> : null}
        </div>

        <div className="global-search-footer">
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">↑↓</kbd> {t("hintSelect")}</span>
          <span className="global-search-footer-hint"><kbd className="global-search-kbd">↵</kbd> {t("hintOpen")}</span>
          {listInput ? <span className="global-search-footer-hint"><kbd className="global-search-kbd">{shortcut("F")}</kbd> {t("hintList")}</span> : null}
        </div>
      </div>
    </Modal>
  );
}
