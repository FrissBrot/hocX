"use client";

import { ReactNode, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";

/**
 * Filter im Spaltenkopf einer DataTable (Spalte als `{ key, label, header: <ColumnFilter …> }`).
 * Der Kopf bleibt die Spaltenbeschriftung; ein Punkt zeigt einen aktiven Filter. Der Inhalt
 * (Datumsfelder, Optionsliste …) liegt im Popover und bekommt `close` zum Schliessen nach der Wahl.
 */
export function ColumnFilter({
  label,
  active,
  align = "start",
  children,
}: {
  label: string;
  active: boolean;
  align?: "start" | "end";
  children: (close: () => void) => ReactNode;
}) {
  const t = useTranslations("common.columnFilter");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`column-filter-trigger${active ? " column-filter-trigger-active" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={active ? t("activeLabel", { column: label }) : t("label", { column: label })}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{label}</span>
        <svg className="column-filter-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M2 3h12l-4.5 5.5V13l-3 1.5V8.5z" />
        </svg>
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef} align={align} className="column-filter-panel">
        {children(() => setOpen(false))}
      </Popover>
    </>
  );
}

export type ColumnFilterOption = { value: string; label: string; hint?: string };

/** Durchsuchbare Einfachauswahl im Spaltenfilter; «Alle» (leerer Wert) hebt den Filter auf. */
export function ColumnFilterOptions({
  options,
  value,
  allLabel,
  onChange,
  searchable = true,
}: {
  options: ColumnFilterOption[];
  value: string;
  allLabel: string;
  onChange: (value: string) => void;
  searchable?: boolean;
}) {
  const tCommon = useTranslations("common");
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  const filtered = needle ? options.filter((option) => option.label.toLowerCase().includes(needle)) : options;
  return (
    <div className="column-filter-options">
      {searchable ? <SearchInput value={search} onChange={setSearch} placeholder={tCommon("searchPlaceholder")} /> : null}
      <div className="column-filter-list">
        {needle ? null : (
          <button type="button" className={`mini-menu-option${value === "" ? " mini-menu-option-active" : ""}`} onClick={() => onChange("")}>
            <span>{allLabel}</span>
          </button>
        )}
        {filtered.length === 0 ? <span className="muted column-filter-empty">{tCommon("noResults")}</span> : null}
        {filtered.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`mini-menu-option${value === option.value ? " mini-menu-option-active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            <span>{option.label}</span>
            {option.hint ? <span className="mini-menu-option-subtle">{option.hint}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}
