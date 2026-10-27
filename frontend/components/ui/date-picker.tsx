"use client";

// Kalender zum Datumsfeld (DateInput): Monatsansicht im hocX-Look statt des nativen Pickers.
// Rechnet nur mit ISO-Daten (JJJJ-MM-TT) in UTC, damit Zeitzonen keine Tage verschieben.
// Wochentags- und Monatsnamen kommen aus der UI-Sprache, die Woche beginnt am Montag.
// Tastatur: Pfeile (Tag/Woche), Bild auf/ab (Monat, mit Shift Jahr), Pos1/Ende (Wochenanfang/
// -ende), Enter/Leertaste wählt, Escape schliesst.

import { KeyboardEvent, RefObject, useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { createPortal } from "react-dom";

import { usePopoverDismiss, usePopoverPosition } from "./popover";

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

function parseIso(value: string | null | undefined): Date | null {
  const match = ISO.exec(value ?? "");
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? null : date;
}

export function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addDays(date: Date, days: number): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + days));
}

/** Monate addieren; der Tag wird auf das Monatsende begrenzt (31.1. + 1 Monat = 29.2.). */
function addMonths(date: Date, months: number): Date {
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + months, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  return new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), Math.min(date.getUTCDate(), lastDay)));
}

function todayUtc(): Date {
  const now = new Date();
  return new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
}

/** Montag = 0 … Sonntag = 6 */
function weekdayIndex(date: Date): number {
  return (date.getUTCDay() + 6) % 7;
}

type Props = {
  anchorRef: RefObject<HTMLElement | null>;
  value: string | null | undefined;
  min?: string;
  max?: string;
  onSelect: (value: string) => void;
  onClose: () => void;
  /** Bekommt den Fokus zurück, wenn der Kalender per Tastatur geschlossen wird */
  returnFocusRef?: RefObject<HTMLElement | null>;
};

export function DatePicker({ anchorRef, value, min, max, onSelect, onClose, returnFocusRef }: Props) {
  const t = useTranslations("common");
  const locale = useLocale();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const style = usePopoverPosition(true, anchorRef, "end", 6, { minWidth: 296, estimatedHeight: 360 });
  const close = () => {
    const hadFocus = panelRef.current?.contains(document.activeElement) ?? false;
    onClose();
    if (hadFocus) returnFocusRef?.current?.focus();
  };
  usePopoverDismiss(true, close, [anchorRef, panelRef]);

  const selected = parseIso(value);
  const minDate = parseIso(min);
  const maxDate = parseIso(max);
  const today = todayUtc();
  const [focused, setFocused] = useState<Date>(() => selected ?? today);

  const outOfRange = (date: Date) => (minDate !== null && date < minDate) || (maxDate !== null && date > maxDate);

  const formats = useMemo(
    () => ({
      title: new Intl.DateTimeFormat(locale, { month: "long", year: "numeric", timeZone: "UTC" }),
      weekday: new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" }),
      weekdayLong: new Intl.DateTimeFormat(locale, { weekday: "long", timeZone: "UTC" }),
      day: new Intl.DateTimeFormat(locale, { dateStyle: "full", timeZone: "UTC" }),
    }),
    [locale]
  );
  // 1.1.2024 war ein Montag
  const weekdays = Array.from({ length: 7 }, (_, index) => new Date(Date.UTC(2024, 0, 1 + index)));

  const monthStart = new Date(Date.UTC(focused.getUTCFullYear(), focused.getUTCMonth(), 1));
  const gridStart = addDays(monthStart, -weekdayIndex(monthStart));
  const days = Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));

  // Fokus folgt dem aktiven Tag (beim Öffnen und bei jeder Tastaturbewegung)
  useEffect(() => {
    gridRef.current?.querySelector<HTMLButtonElement>(`[data-date="${toIsoDate(focused)}"]`)?.focus();
  }, [focused]);

  function choose(date: Date) {
    if (outOfRange(date)) return;
    onSelect(toIsoDate(date));
    close();
  }

  function onGridKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, () => Date> = {
      ArrowLeft: () => addDays(focused, -1),
      ArrowRight: () => addDays(focused, 1),
      ArrowUp: () => addDays(focused, -7),
      ArrowDown: () => addDays(focused, 7),
      PageUp: () => addMonths(focused, event.shiftKey ? -12 : -1),
      PageDown: () => addMonths(focused, event.shiftKey ? 12 : 1),
      Home: () => addDays(focused, -weekdayIndex(focused)),
      End: () => addDays(focused, 6 - weekdayIndex(focused)),
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      setFocused(move());
    }
  }

  if (typeof document === "undefined") return null;
  return createPortal(
    <div ref={panelRef} className="popover-panel date-picker" style={style} role="dialog" aria-label={t("dateField.calendar")}>
      <div className="date-picker-header">
        <button type="button" className="button-icon-soft" aria-label={t("dateField.previousMonth")} onClick={() => setFocused(addMonths(focused, -1))}>
          ‹
        </button>
        <span className="date-picker-title" aria-live="polite">
          {formats.title.format(monthStart)}
        </span>
        <button type="button" className="button-icon-soft" aria-label={t("dateField.nextMonth")} onClick={() => setFocused(addMonths(focused, 1))}>
          ›
        </button>
      </div>
      <div className="date-picker-weekdays" aria-hidden="true">
        {weekdays.map((day) => (
          <span key={day.getUTCDay()} title={formats.weekdayLong.format(day)}>
            {formats.weekday.format(day)}
          </span>
        ))}
      </div>
      <div ref={gridRef} className="date-picker-grid" onKeyDown={onGridKeyDown}>
        {days.map((day) => {
          const iso = toIsoDate(day);
          const isSelected = selected !== null && iso === toIsoDate(selected);
          const isFocused = iso === toIsoDate(focused);
          const classes = [
            "date-picker-day",
            day.getUTCMonth() !== monthStart.getUTCMonth() ? "date-picker-day-outside" : "",
            iso === toIsoDate(today) ? "date-picker-day-today" : "",
            isSelected ? "date-picker-day-selected" : "",
          ].filter(Boolean);
          return (
            <button
              key={iso}
              type="button"
              data-date={iso}
              className={classes.join(" ")}
              tabIndex={isFocused ? 0 : -1}
              disabled={outOfRange(day)}
              aria-label={formats.day.format(day)}
              aria-pressed={isSelected}
              aria-current={iso === toIsoDate(today) ? "date" : undefined}
              onClick={() => choose(day)}
            >
              {day.getUTCDate()}
            </button>
          );
        })}
      </div>
      <div className="date-picker-footer">
        <button type="button" className="button-ghost" disabled={outOfRange(today)} onClick={() => choose(today)}>
          {t("dateField.today")}
        </button>
      </div>
    </div>,
    document.body
  );
}
