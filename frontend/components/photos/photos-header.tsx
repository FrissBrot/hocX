"use client";

import { ReactNode, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileSegmented } from "@/components/mobile/mobile-ui";
import { ActionIcon } from "@/components/ui/action-icons";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { formatInteger } from "@/lib/utils/format";

// Kopf und Werkzeugkasten der Fotoseite nach Design «hocX Fotos Header 1a»
// (Spezifikation: Titel + Zähler, Lead, Papierkorb/Hochladen; Karte mit Reitern, Suche,
// Sortierung, Tags und darunter Anzahl, aktive Filter und «Filter zurücksetzen»).

export type PhotosTab = "all" | "albums" | "duplicates" | "series";

export type PhotosSortOption = { id: string; label: string };

type HeaderProps = {
  /** Alle Fotos der Organisation (Zähler neben dem Titel); null solange unbekannt. */
  total: number | null;
  /** Hinweise rechts vor den Knöpfen (Analyse läuft, Upload läuft). */
  pills?: ReactNode;
  onOpenTrash?: () => void;
  onUpload: () => void;
};

export function PhotosPageHeader({ total, pills, onOpenTrash, onUpload }: HeaderProps) {
  const t = useTranslations("photos.view");
  const tFiles = useTranslations("files");
  const locale = useLocale();
  return (
    <div className="page-header photos-page-header">
      <div>
        <div className="photos-title-row">
          <h1 className="page-title">{t("pageTitle")}</h1>
          {total !== null ? (
            <span className="photos-count-pill" aria-label={t("header.countLabel", { count: total })}>
              {formatInteger(total, locale)}
            </span>
          ) : null}
        </div>
        <p className="muted photos-lead">{t("description")}</p>
      </div>
      <div className="table-toolbar-actions photos-header-actions">
        {pills}
        {onOpenTrash ? (
          <button type="button" className="button-secondary photos-header-button" onClick={onOpenTrash}>
            <ActionIcon name="delete" />
            {tFiles("trash.open")}
          </button>
        ) : null}
        <button type="button" className="button-primary photos-upload-button" onClick={onUpload}>
          <ActionIcon name="add" />
          {t("uploadButton")}
        </button>
      </div>
    </div>
  );
}

type ToolbarProps = {
  mobile?: boolean;
  tab: PhotosTab;
  onTabChange: (tab: PhotosTab) => void;
  search: string;
  onSearchChange: (value: string) => void;
  /** Sortierung und Tag-Filter nur in Ansichten mit Liste (nicht Alben, nicht mobil). */
  showSort: boolean;
  sortOptions: PhotosSortOption[];
  sortId: string;
  onSortChange: (id: string) => void;
  showTags: boolean;
  tags: string[];
  onTagsChange: (tags: string[]) => void;
  tagSuggestions: string[];
  /** Treffer der aktuellen Filter (null: unbekannt/lädt) und Gesamtzahl. */
  resultCount: number | null;
  total: number | null;
  /** Suche (aktiv getippt, nicht entprellt) für die Filter-Chips. */
  activeSearch: string;
  onReset: () => void;
};

function SortIcon() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M7 4v16M3.5 7.5 7 4l3.5 3.5M17 20V4M13.5 16.5 17 20l3.5-3.5" />
    </svg>
  );
}

function TagIcon() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
      <circle cx="7.5" cy="7.5" r="1.5" />
    </svg>
  );
}

export function PhotosToolbar({
  mobile = false,
  tab,
  onTabChange,
  search,
  onSearchChange,
  showSort,
  sortOptions,
  sortId,
  onSortChange,
  showTags,
  tags,
  onTagsChange,
  tagSuggestions,
  resultCount,
  total,
  activeSearch,
  onReset,
}: ToolbarProps) {
  const t = useTranslations("photos.view");
  const locale = useLocale();
  const [sortOpen, setSortOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const sortRef = useRef<HTMLButtonElement | null>(null);
  const tagsRef = useRef<HTMLButtonElement | null>(null);
  const tabOptions = [
    { value: "all" as const, label: t("tabs.all") },
    { value: "albums" as const, label: t("tabs.albums") },
    { value: "duplicates" as const, label: t("tabs.duplicates") },
    { value: "series" as const, label: t("tabs.series") },
  ];
  const listTab = tab !== "albums";
  const query = activeSearch.trim();
  const filtersActive = listTab && (query !== "" || tags.length > 0);
  const currentSort = sortOptions.find((option) => option.id === sortId) ?? sortOptions[0];

  return (
    <div className="photos-toolbar">
      <div className="photos-toolbar-main">
        {mobile ? (
          <MobileSegmented<PhotosTab> ariaLabel={t("pageTitle")} value={tab} onChange={onTabChange} options={tabOptions} />
        ) : (
          <FilterTabs options={tabOptions} value={tab} onChange={onTabChange} />
        )}
        {listTab ? (
          <div className="photos-toolbar-search">
            <SearchInput
              value={search}
              onChange={onSearchChange}
              placeholder={t("searchPlaceholder")}
              aria-label={t("toolbar.searchLabel")}
              clearLabel={t("toolbar.clearSearch")}
            />
          </div>
        ) : null}
        {listTab && showSort && currentSort ? (
          <>
            <button
              ref={sortRef}
              type="button"
              className="button-secondary photos-toolbar-button"
              aria-haspopup="menu"
              aria-expanded={sortOpen}
              aria-label={t("toolbar.sortLabel", { current: currentSort.label })}
              onClick={() => setSortOpen((open) => !open)}
            >
              <SortIcon />
              <span className="photos-toolbar-button-label">{currentSort.label}</span>
            </button>
            <Popover open={sortOpen} onOpenChange={setSortOpen} anchorRef={sortRef} align="end" className="photos-sort-panel">
              {sortOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={option.id === currentSort.id}
                  className={`mini-menu-option${option.id === currentSort.id ? " mini-menu-option-active" : ""}`}
                  onClick={() => {
                    onSortChange(option.id);
                    setSortOpen(false);
                  }}
                >
                  <span>{option.label}</span>
                </button>
              ))}
            </Popover>
          </>
        ) : null}
        {listTab && showTags ? (
          <>
            <button
              ref={tagsRef}
              type="button"
              className={`button-secondary photos-toolbar-button${tags.length > 0 ? " photos-toolbar-button-active" : ""}`}
              aria-haspopup="dialog"
              aria-expanded={tagsOpen}
              onClick={() => setTagsOpen((open) => !open)}
            >
              <TagIcon />
              {tags.length > 0 ? t("toolbar.tagsButtonCount", { count: tags.length }) : t("toolbar.tagsButton")}
            </button>
            <Popover open={tagsOpen} onOpenChange={setTagsOpen} anchorRef={tagsRef} align="end" className="photos-tags-panel">
              <TagInput
                value={tags.join(",")}
                onChange={(value) => onTagsChange(value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [])}
                suggestions={tagSuggestions}
                placeholder={t("tagPlaceholder")}
              />
            </Popover>
          </>
        ) : null}
      </div>
      {filtersActive ? (
        <div className="photos-toolbar-status" role="status">
          <span className="photos-toolbar-count">
            {resultCount === null
              ? t("toolbar.searching")
              : total !== null
                ? t("toolbar.resultCount", {
                    count: formatInteger(resultCount, locale),
                    total: formatInteger(total, locale),
                    totalValue: total,
                  })
                : t("toolbar.resultCountOnly", { count: formatInteger(resultCount, locale), countValue: resultCount })}
          </span>
          {query ? (
            <span className="photos-filter-chip">
              {t("toolbar.searchChip", { query })}
              <button
                type="button"
                className="photos-filter-chip-remove"
                aria-label={t("toolbar.clearSearch")}
                onClick={() => onSearchChange("")}
              >
                <ActionIcon name="close" width={12} height={12} />
              </button>
            </span>
          ) : null}
          {tags.map((tag) => (
            <span key={tag} className="photos-filter-chip">
              {tag}
              <button
                type="button"
                className="photos-filter-chip-remove"
                aria-label={t("toolbar.removeTag", { tag })}
                onClick={() => onTagsChange(tags.filter((current) => current !== tag))}
              >
                <ActionIcon name="close" width={12} height={12} />
              </button>
            </span>
          ))}
          <button type="button" className="photos-filter-reset" onClick={onReset}>
            {t("toolbar.reset")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Leerer Zustand, wenn Suche/Filter nichts finden. */
export function PhotosNoResults({ query, onReset }: { query: string; onReset: () => void }) {
  const t = useTranslations("photos.view");
  const trimmed = query.trim();
  return (
    <div className="photos-no-results" role="status">
      <strong>{trimmed ? t("noResultsFor", { query: trimmed }) : t("noResultsFiltered")}</strong>
      <p className="muted">
        {t.rich("noResultsHint", {
          reset: (chunks) => (
            <button type="button" className="photos-filter-reset photos-filter-reset-inline" onClick={onReset}>
              {chunks}
            </button>
          ),
        })}
      </p>
    </div>
  );
}
