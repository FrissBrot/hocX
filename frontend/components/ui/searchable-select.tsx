"use client";

import { ButtonHTMLAttributes, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";

import { Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";

type BaseProps<T> = {
  options: T[];
  getLabel: (option: T) => string;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyLabel?: string;
  disabled?: boolean;
  className?: string;
  /** Extra attributes spread onto the trigger button - e.g. data-form-input/onKeyDown
   * for a form's custom Tab-order handling, matching what a native <select> replaced
   * by this component could carry directly. */
  triggerProps?: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type" | "onClick" | "className" | "disabled"> &
    Record<`data-${string}`, unknown>;
};

type SingleProps<T, Id extends string | number> = BaseProps<T> & {
  getId: (option: T) => Id;
  value: Id | null;
  onChange: (option: T | null) => void;
  /** Label for a clearable "no selection" entry. Omit to make a selection required. */
  nullLabel?: string;
};

// Generic searchable dropdown replacing a native <select> whose options are loaded
// dynamically (from an API/DB), so those pickers get the same Popover + search-filter
// pattern as TodoAssigneeMenu instead of an unsearchable native list. Single-select;
// see SearchableMultiSelect for the multi-value variant.
//
// Id is inferred from getId's return type and pins `value`/onChange's option ids to
// that same type, so passing e.g. a string filter-state against numeric option ids
// (an easy mistake - native <select> values are always strings, these aren't) is a
// compile error instead of a silently-never-matching runtime comparison.
export function SearchableSelect<T, Id extends string | number>({
  options,
  getId,
  getLabel,
  value,
  onChange,
  nullLabel,
  placeholder = "Auswählen",
  searchPlaceholder = "Suchen…",
  emptyLabel = "Keine Ergebnisse",
  disabled,
  className,
  triggerProps,
}: SingleProps<T, Id>) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const filtered = search.trim()
    ? options.filter((o) => getLabel(o).toLowerCase().includes(search.trim().toLowerCase()))
    : options;
  const selected = options.find((o) => getId(o) === value) ?? null;
  const triggerLabel = selected ? getLabel(selected) : nullLabel ?? placeholder;

  useEffect(() => {
    setHighlighted(0);
  }, [search, open]);

  useEffect(() => {
    if (!open) {
      setSearch("");
    }
  }, [open]);

  // See todo-assignee-menu.tsx for why this is a useLayoutEffect focus rather than
  // the autoFocus prop (avoids the portaled panel jumping the page before it's
  // positioned).
  useLayoutEffect(() => {
    if (open) {
      searchRef.current?.focus({ preventScroll: true });
    }
  }, [open]);

  function pick(option: T | null) {
    onChange(option);
    setOpen(false);
  }

  function handleInputKey(event: KeyboardEvent<HTMLInputElement>) {
    const offset = nullLabel ? 1 : 0;
    const count = filtered.length + offset;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = Math.min(highlighted + 1, count - 1);
      setHighlighted(next);
      (listRef.current?.children[next] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const prev = Math.max(highlighted - 1, 0);
      setHighlighted(prev);
      (listRef.current?.children[prev] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (nullLabel && highlighted === 0) {
        pick(null);
      } else {
        const option = filtered[highlighted - offset];
        if (option) {
          pick(option);
        }
      }
    }
  }

  return (
    <div className={`mini-menu mini-menu-compact${className ? ` ${className}` : ""}`}>
      <button
        ref={triggerRef}
        type="button"
        className={`mini-menu-trigger${open ? " mini-menu-trigger-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        {...triggerProps}
      >
        <span className="mini-menu-trigger-label">{triggerLabel}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef} className="assignee-popover-portal">
        <SearchInput ref={searchRef} value={search} onChange={setSearch} placeholder={searchPlaceholder} onKeyDown={handleInputKey} />
        <div className="menu-list" role="listbox" ref={listRef}>
          {nullLabel ? (
            <button
              type="button"
              role="option"
              aria-selected={value === null}
              className={`menu-item${value === null ? " menu-item-selected" : ""}${highlighted === 0 ? " menu-item-highlighted" : ""}`}
              onMouseEnter={() => setHighlighted(0)}
              onClick={() => pick(null)}
            >
              <span className="menu-item-label">{nullLabel}</span>
              {value === null ? <span className="menu-item-check">✓</span> : null}
            </button>
          ) : null}
          {filtered.length === 0 && !nullLabel ? (
            <span className="assignee-empty">{emptyLabel}</span>
          ) : (
            filtered.map((option, index) => {
              const id = getId(option);
              const rowIndex = index + (nullLabel ? 1 : 0);
              return (
                <button
                  key={id}
                  type="button"
                  role="option"
                  aria-selected={id === value}
                  className={`menu-item${id === value ? " menu-item-selected" : ""}${rowIndex === highlighted ? " menu-item-highlighted" : ""}`}
                  onMouseEnter={() => setHighlighted(rowIndex)}
                  onClick={() => pick(option)}
                >
                  <span className="menu-item-label">{getLabel(option)}</span>
                  {id === value ? <span className="menu-item-check">✓</span> : null}
                </button>
              );
            })
          )}
        </div>
      </Popover>
    </div>
  );
}

type MultiProps<T, Id extends string | number> = BaseProps<T> & {
  getId: (option: T) => Id;
  values: Id[];
  onChange: (ids: Id[]) => void;
  /** Trigger label when nothing is selected. Defaults to `placeholder`. */
  emptySelectionLabel?: string;
};

// Multi-select counterpart to SearchableSelect: toggles membership on click and keeps
// the popover open across picks, closing only via Escape/outside-click. See
// SearchableSelect's doc comment for why Id is its own generic parameter.
export function SearchableMultiSelect<T, Id extends string | number>({
  options,
  getId,
  getLabel,
  values,
  onChange,
  placeholder = "Auswählen",
  emptySelectionLabel,
  searchPlaceholder = "Suchen…",
  emptyLabel = "Keine Ergebnisse",
  disabled,
  className,
  triggerProps,
}: MultiProps<T, Id>) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const filtered = search.trim()
    ? options.filter((o) => getLabel(o).toLowerCase().includes(search.trim().toLowerCase()))
    : options;

  const selectedSet = new Set(values);
  let triggerLabel = emptySelectionLabel ?? placeholder;
  if (values.length === 1) {
    const only = options.find((o) => getId(o) === values[0]);
    if (only) {
      triggerLabel = getLabel(only);
    }
  } else if (values.length > 1) {
    triggerLabel = `${values.length} ausgewählt`;
  }

  useEffect(() => {
    if (!open) {
      setSearch("");
    }
  }, [open]);

  useLayoutEffect(() => {
    if (open) {
      searchRef.current?.focus({ preventScroll: true });
    }
  }, [open]);

  function toggle(id: Id) {
    onChange(selectedSet.has(id) ? values.filter((v) => v !== id) : [...values, id]);
  }

  return (
    <div className={`mini-menu mini-menu-compact${className ? ` ${className}` : ""}`}>
      <button
        ref={triggerRef}
        type="button"
        className={`mini-menu-trigger${open ? " mini-menu-trigger-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        {...triggerProps}
      >
        <span className="mini-menu-trigger-label">{triggerLabel}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef} className="assignee-popover-portal">
        <SearchInput ref={searchRef} value={search} onChange={setSearch} placeholder={searchPlaceholder} />
        <div className="menu-list" role="listbox">
          {filtered.length === 0 ? (
            <span className="assignee-empty">{emptyLabel}</span>
          ) : (
            filtered.map((option) => {
              const id = getId(option);
              const isSelected = selectedSet.has(id);
              return (
                <button
                  key={id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  className={`menu-item${isSelected ? " menu-item-selected" : ""}`}
                  onClick={() => toggle(id)}
                >
                  <span className="menu-item-label">{getLabel(option)}</span>
                  {isSelected ? <span className="menu-item-check">✓</span> : null}
                </button>
              );
            })
          )}
        </div>
      </Popover>
    </div>
  );
}
