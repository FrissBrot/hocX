"use client";

import { useRef, useState } from "react";

import { Menu, MenuItem, Popover } from "@/components/ui/popover";
import type { BadgeVariant } from "@/components/ui/badge";

export type PillMenuOption<T extends string> = { value: T; label: string; variant: BadgeVariant };

type Props<T extends string> = {
  value: T;
  options: PillMenuOption<T>[];
  onChange: (value: T) => void;
};

// Colored pill trigger (same look as the read-only Badge) that opens the app's
// standard Popover/menu-item dropdown, replacing a native <select> so Rolle/Status
// pickers match the rest of the app's dropdown pattern (e.g. TodoAssigneeMenu).
export function PillMenu<T extends string>({ value, options, onChange }: Props<T>) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const current = options.find((option) => option.value === value) ?? options[0];

  return (
    <div className="mini-menu mini-menu-compact" style={{ minWidth: 0 }}>
      <button
        ref={triggerRef}
        type="button"
        className={`pill-menu-trigger${open ? " pill-menu-trigger-open" : ""}`}
        data-variant={current.variant}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span>{current.label}</span>
        <span className="pill-menu-trigger-icon" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="12" height="12" fill="none">
            <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef}>
        <Menu>
          {options.map((option) => (
            <MenuItem
              key={option.value}
              selected={option.value === value}
              onSelect={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >
              {option.label}
            </MenuItem>
          ))}
        </Menu>
      </Popover>
    </div>
  );
}
