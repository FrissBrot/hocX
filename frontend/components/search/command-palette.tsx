"use client";

import { KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { highlightMatch } from "@/lib/search/match";

/** Ein Treffer der Befehlspalette - die Gruppe ist ein freier Schlüssel des Aufrufers. */
export type PaletteEntry<TGroup extends string = string> = {
  id: string;
  group: TGroup;
  label: string;
  sublabel?: string;
  icon?: ReactNode;
};

/**
 * Präsentationale Befehlspalette (Ctrl+K / ⌘K): Dialog ohne Kopf, Suchfeld als Combobox, Listbox
 * mit aria-activedescendant, Pfeile/Enter/Esc, Gruppenüberschriften in der Reihenfolge der
 * Einträge, Treffer-Hervorhebung und Fusszeile. Woher die Einträge kommen (Navigation, Server,
 * zuletzt geöffnet) entscheidet der Aufrufer - die Mandanten-Suche (GlobalSearch) und die
 * Admin-Suche (AdminCommandPalette) nutzen beide diese Komponente.
 */
export function CommandPalette<TGroup extends string>({
  open,
  onClose,
  title,
  query,
  onQueryChange,
  entries,
  groupLabel,
  onSelect,
  placeholder,
  emptyText,
  status,
  footer,
  onInputKeyDown,
  inputRef,
  idPrefix = "command-palette",
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  query: string;
  onQueryChange: (value: string) => void;
  entries: PaletteEntry<TGroup>[];
  /** Überschrift einer Gruppe; null = ohne Überschrift */
  groupLabel: (group: TGroup) => string | null;
  onSelect: (entry: PaletteEntry<TGroup>) => void;
  placeholder: string;
  /** Text, wenn keine Einträge da sind */
  emptyText: string;
  /** Statuszeile unter der Liste (Laden, Fehler) */
  status?: ReactNode;
  footer?: ReactNode;
  /** Zusätzliche Tasten im Suchfeld (vor der Standardbehandlung); true = erledigt */
  onInputKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => boolean;
  /** Ref-Callback des Suchfelds (Fokus beim Montieren, vorab getippte Zeichen) */
  inputRef?: (element: HTMLInputElement | null) => void;
  idPrefix?: string;
  className?: string;
}) {
  const [activeIndex, setActiveIndex] = useState(0);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const trimmed = query.trim();

  useEffect(() => {
    setActiveIndex(0);
  }, [trimmed]);

  useEffect(() => {
    itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, entries.length]);

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (onInputKeyDown?.(event)) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => Math.min(entries.length - 1, current + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(0, current - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const entry = entries[Math.min(activeIndex, entries.length - 1)];
      if (entry) onSelect(entry);
    }
  }

  const listId = `${idPrefix}-results`;
  const activeId = entries[activeIndex] ? `${idPrefix}-option-${activeIndex}` : undefined;
  let lastGroup: TGroup | null = null;

  return (
    <Modal open={open} onClose={onClose} title={title} hideHeader className={["global-search-shell", className].filter(Boolean).join(" ")}>
      <div className="global-search" data-global-search>
        <div className="global-search-field-row">
          <SearchInput
            ref={inputRef}
            autoFocus
            value={query}
            onChange={onQueryChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="global-search-input"
            aria-label={title}
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={activeId}
            aria-autocomplete="list"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="global-search-kbd">Esc</kbd>{/* i18n-ok: Tastenname, sprachunabhaengig */}
        </div>

        <div className="global-search-list" id={listId} role="listbox" aria-label={title}>
          {entries.length === 0 ? (
            <div className="global-search-empty">{emptyText}</div>
          ) : (
            entries.map((entry, index) => {
              const label = entry.group !== lastGroup ? groupLabel(entry.group) : null;
              const heading = label ? <div className="global-search-group" role="presentation">{label}</div> : null;
              lastGroup = entry.group;
              const active = index === activeIndex;
              return (
                <div key={entry.id} role="presentation">
                  {heading}
                  <button
                    id={`${idPrefix}-option-${index}`}
                    type="button"
                    role="option"
                    aria-selected={active}
                    tabIndex={-1}
                    ref={(node) => { itemRefs.current[index] = node; }}
                    className={`global-search-item${active ? " global-search-item-active" : ""}`}
                    onMouseMove={() => { if (index !== activeIndex) setActiveIndex(index); }}
                    onClick={() => onSelect(entry)}
                  >
                    <span className="global-search-item-icon" aria-hidden="true">
                      {entry.icon ?? <span className="global-search-item-dot" />}
                    </span>
                    <span className="global-search-item-text">
                      <span className="global-search-item-title">
                        {highlightMatch(entry.label, trimmed).map((segment, segmentIndex) =>
                          segment.hit ? <mark key={segmentIndex} className="global-search-hit">{segment.text}</mark> : <span key={segmentIndex}>{segment.text}</span>,
                        )}
                      </span>
                      {entry.sublabel ? <span className="global-search-item-sub">{entry.sublabel}</span> : null}
                    </span>
                  </button>
                </div>
              );
            })
          )}
          {status}
        </div>

        {footer ? <div className="global-search-footer">{footer}</div> : null}
      </div>
    </Modal>
  );
}
