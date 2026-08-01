"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";

import { Popover } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";

export type AssigneeOption = { id: number | null; display_name: string };

type Props = {
  label: string;
  participants: AssigneeOption[];
  activeId: number | null;
  onChange: (option: AssigneeOption) => void;
};

export function TodoAssigneeMenu({ label, participants, activeId, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const options: AssigneeOption[] = [{ id: null, display_name: "Niemand" }, ...participants];
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
        <SearchInput value={search} onChange={setSearch} placeholder="Suchen…" onKeyDown={handleInputKey} autoFocus />
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
