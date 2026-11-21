"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Popover } from "@/components/ui/popover";

// Spaltenwahl der Admin-Tabellen (Plan §5.1): Popover mit .mini-menu-*-Schaltern (DESIGN §5.4),
// je Admin im Browser gespeichert (localStorage `hocx-admin-cols:<tabelle>`). Nur Komfort - fehlt
// der Speicher (privates Fenster), gelten die Standardspalten.

export type ColumnDef = { key: string; label: string; /** immer sichtbar (z. B. Name) */ required?: boolean; /** standardmässig aus */ hidden?: boolean };

const STORAGE_PREFIX = "hocx-admin-cols:";

export function defaultVisibleColumns(columns: ColumnDef[]): string[] {
  return columns.filter((column) => column.required || !column.hidden).map((column) => column.key);
}

/** Gespeicherte Auswahl lesen; unbekannte Schlüssel fallen weg, Pflichtspalten sind immer dabei. */
export function readVisibleColumns(table: string, columns: ColumnDef[]): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + table);
    if (!raw) return defaultVisibleColumns(columns);
    const stored = JSON.parse(raw);
    if (!Array.isArray(stored)) return defaultVisibleColumns(columns);
    const known = new Set(columns.map((column) => column.key));
    const picked = new Set(stored.filter((key): key is string => typeof key === "string" && known.has(key)));
    return columns.filter((column) => column.required || picked.has(column.key)).map((column) => column.key);
  } catch {
    return defaultVisibleColumns(columns);
  }
}

export function useColumnVisibility(table: string, columns: ColumnDef[]) {
  const columnsRef = useRef(columns);
  columnsRef.current = columns;
  // Erst nach dem Mounten aus localStorage lesen (Server-Render kennt nur die Standardspalten)
  const [visible, setVisible] = useState<string[]>(() => defaultVisibleColumns(columns));
  useEffect(() => {
    setVisible(readVisibleColumns(table, columnsRef.current));
  }, [table]);

  const toggle = useCallback(
    (key: string) => {
      setVisible((current) => {
        const column = columnsRef.current.find((item) => item.key === key);
        if (!column || column.required) return current;
        const next = current.includes(key) ? current.filter((item) => item !== key) : [...current, key];
        const ordered = columnsRef.current.map((item) => item.key).filter((item) => next.includes(item));
        try {
          window.localStorage.setItem(STORAGE_PREFIX + table, JSON.stringify(ordered));
        } catch {
          // nur Komfort
        }
        return ordered;
      });
    },
    [table],
  );
  const isVisible = useCallback((key: string) => visible.includes(key), [visible]);
  return { visible, isVisible, toggle };
}

export function ColumnPicker({ columns, isVisible, onToggle }: { columns: ColumnDef[]; isVisible: (key: string) => boolean; onToggle: (key: string) => void }) {
  const t = useTranslations("adminShell.columns");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="button-secondary button-ghost"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {t("trigger")}
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={triggerRef} align="end" className="mini-menu-popover-portal">
        <div className="mini-menu-section" role="group" aria-label={t("title")}>
          <div className="mini-menu-section-title">{t("title")}</div>
          {columns.map((column) => (
            <label key={column.key} className="mini-menu-option mini-menu-switch-option">
              <span>{column.label}</span>
              <input
                type="checkbox"
                className="mini-menu-switch-input"
                checked={column.required || isVisible(column.key)}
                disabled={column.required}
                onChange={() => onToggle(column.key)}
              />
              <span className="mini-menu-switch" aria-hidden="true" />
            </label>
          ))}
        </div>
      </Popover>
    </>
  );
}
