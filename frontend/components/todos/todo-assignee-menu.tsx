"use client";

import { KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";

import { Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";

// Id defaults to number (todo assignees, participant/event/list ids - all existing
// callers) but is generic so a caller keyed by string (e.g. a Matrix column_key) can
// instantiate TodoAssigneeMenu<string> instead of widening every other call site's
// type to a union.
export type AssigneeOption<Id extends string | number = number> = { id: Id | null; display_name: string };

type Props<Id extends string | number> = {
  label: string;
  participants: AssigneeOption<Id>[];
  activeId: Id | null;
  onChange: (option: AssigneeOption<Id>) => void;
  /** Text for the built-in "id: null" option - defaults to the todo-assignee wording
   * ("Niemand") but callers reusing this as a generic searchable dropdown (e.g. picking
   * an existing record vs. creating a new one) pass their own, e.g. "Neu anlegen". */
  nullLabel?: string;
};

export function TodoAssigneeMenu<Id extends string | number = number>({
  label,
  participants,
  activeId,
  onChange,
  nullLabel = "Niemand",
}: Props<Id>) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const options: AssigneeOption<Id>[] = [{ id: null, display_name: nullLabel }, ...participants];
  const filtered = search.trim()
    ? options.filter((o) => o.display_name.toLowerCase().includes(search.trim().toLowerCase()))
    : options;

  useEffect(() => {
    setHighlighted(0);
  }, [search, open]);

  useEffect(() => {
    if (!open) {
      setSearch("");
    }
  }, [open]);

  // Deliberately not the `autoFocus` prop: React applies that during the DOM-mutation
  // part of the commit, before Popover's own useLayoutEffect has positioned the portaled
  // panel - the browser then scroll-into-views the still-unpositioned panel (appended at
  // the end of <body>), jumping the whole page to the bottom. Focusing here, in a
  // useLayoutEffect on the parent, runs after Popover's (child) positioning effect, and
  // `preventScroll` is a second line of defense against the page jumping regardless.
  useLayoutEffect(() => {
    if (open) {
      searchRef.current?.focus({ preventScroll: true });
    }
  }, [open]);

  function handleInputKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = Math.min(highlighted + 1, filtered.length - 1);
      setHighlighted(next);
      (listRef.current?.children[next] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const prev = Math.max(highlighted - 1, 0);
      setHighlighted(prev);
      (listRef.current?.children[prev] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filtered[highlighted];
      if (option) {
        onChange(option);
        setOpen(false);
      }
    }
  }

  return (
    <div className="mini-menu mini-menu-compact">
      <button
        ref={triggerRef}
        type="button"
        className={`mini-menu-trigger${open ? " mini-menu-trigger-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="mini-menu-trigger-label">{label}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef} className="assignee-popover-portal">
        <SearchInput ref={searchRef} value={search} onChange={setSearch} placeholder="Suchen…" onKeyDown={handleInputKey} />
        <div className="menu-list" role="listbox" ref={listRef}>
          {filtered.length === 0 ? (
            <span className="assignee-empty">Keine Ergebnisse</span>
          ) : (
            filtered.map((option, index) => (
              <button
                key={option.id ?? "none"}
                type="button"
                role="option"
                aria-selected={option.id === activeId}
                className={`menu-item${option.id === activeId ? " menu-item-selected" : ""}${index === highlighted ? " menu-item-highlighted" : ""}`}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => {
                  onChange(option);
                  setOpen(false);
                }}
              >
                <span className="menu-item-label">{option.display_name}</span>
                {option.id === activeId ? <span className="menu-item-check">✓</span> : null}
              </button>
            ))
          )}
        </div>
      </Popover>
    </div>
  );
}
