"use client";

// Zeitfeld im hocX-Look statt <input type="time">: Eingabe per Tastatur (930, 9.30, 9:30 → 09:30),
// dazu eine Liste im Viertelstunden-Takt (gleiche Optik wie Select). Wert immer «HH:MM» oder "".

import { CSSProperties, FocusEvent, InputHTMLAttributes, KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { createPortal } from "react-dom";

import { computePopoverPosition, usePopoverDismiss } from "./popover";

/** «HH:MM» aus einer Eingabe wie 9, 930, 0930, 9:30 oder 9.30; null, wenn ungültig. */
export function parseTimeInputValue(raw: string): string | null {
  const text = raw.trim();
  const match = /^(\d{1,2})(?:[:.h]?(\d{2}))?$/.exec(text) ?? /^(\d{1,2})(\d{2})$/.exec(text);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2] ?? "0");
  if (hours > 23 || minutes > 59) return null;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

type TimeInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange" | "step"> & {
  value: string | null | undefined;
  onChange: (value: string) => void;
  /** Abstand der Vorschläge in Minuten */
  step?: number;
};

export function TimeInput({ value, onChange, className, disabled, readOnly, placeholder = "hh:mm", onBlur, step = 15, ...props }: TimeInputProps) {
  const t = useTranslations("common");
  const [display, setDisplay] = useState(value ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [style, setStyle] = useState<CSSProperties>({});
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const options = Array.from({ length: Math.ceil((24 * 60) / step) }, (_, index) => {
    const minutes = index * step;
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  });

  useEffect(() => setDisplay(value ?? ""), [value]);

  const close = () => setOpen(false);
  usePopoverDismiss(open, close, [wrapperRef, panelRef]);

  useEffect(() => {
    if (!open || active < 0) return;
    panelRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView?.({ block: "center" });
  }, [open, active]);

  function commit(raw: string, input: HTMLInputElement | null) {
    if (!raw.trim()) {
      input?.setCustomValidity("");
      onChange("");
      return;
    }
    const normalized = parseTimeInputValue(raw);
    if (!normalized) {
      input?.setCustomValidity(t("timeField.invalidFormat"));
      return;
    }
    input?.setCustomValidity("");
    setDisplay(normalized);
    onChange(normalized);
  }

  function openList() {
    if (disabled || readOnly || !wrapperRef.current) return;
    // Nächster Vorschlag ab der aktuellen Zeit (oder 08:00 ohne Wert)
    const current = parseTimeInputValue(display) ?? "08:00";
    const index = options.findIndex((option) => option >= current);
    setActive(index < 0 ? options.length - 1 : index);
    const position = computePopoverPosition(wrapperRef.current.getBoundingClientRect(), "start", 4, { estimatedHeight: 280 });
    // Höchstens sieben Einträge sichtbar, der Rest scrollt
    setStyle({ ...position, maxHeight: Math.min(280, Number(position.maxHeight) || 280) });
    setOpen(true);
  }

  function choose(index: number) {
    const option = options[index];
    if (!option) return;
    setDisplay(option);
    onChange(option);
    setOpen(false);
    buttonRef.current?.focus();
  }

  function onButtonKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openList();
      }
      return;
    }
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 4, PageUp: -4 };
    if (event.key in moves) {
      event.preventDefault();
      setActive((current) => Math.min(options.length - 1, Math.max(0, current + moves[event.key])));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Tab") {
      close();
    }
  }

  return (
    <div ref={wrapperRef} className={`date-input time-input${className ? ` ${className}` : ""}`}>
      <input
        {...props}
        type="text"
        value={display}
        disabled={disabled}
        readOnly={readOnly}
        inputMode="numeric"
        autoComplete="off"
        placeholder={placeholder}
        className="date-input-field"
        onChange={(event) => {
          setDisplay(event.target.value);
          const normalized = event.target.value.trim() ? parseTimeInputValue(event.target.value) : "";
          if (normalized !== null && /^\d{1,2}[:.h]\d{2}$|^$/.test(event.target.value.trim())) {
            event.target.setCustomValidity("");
            onChange(normalized);
          }
        }}
        onBlur={(event: FocusEvent<HTMLInputElement>) => {
          commit(event.target.value, event.target);
          if (event.target.validationMessage) event.target.reportValidity();
          onBlur?.(event);
        }}
      />
      <button
        ref={buttonRef}
        type="button"
        className="date-input-picker"
        disabled={disabled || readOnly}
        aria-label={t("timeField.chooseTime")}
        title={t("timeField.chooseTime")}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onButtonKeyDown}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panelRef}
              id={listId}
              role="listbox"
              aria-label={t("timeField.chooseTime")}
              className="popover-panel select-list time-input-list"
              style={style}
              onMouseDown={(event) => event.preventDefault()}
            >
              {options.map((option, index) => (
                <div
                  key={option}
                  id={`${listId}-${index}`}
                  data-index={index}
                  role="option"
                  aria-selected={option === value}
                  className={["select-option", option === value ? "select-option-selected" : "", index === active ? "select-option-active" : ""].filter(Boolean).join(" ")}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(index)}
                >
                  <span className="select-option-label">{option}</span>
                </div>
              ))}
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
