"use client";

import { FocusEvent, InputHTMLAttributes, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { DatePicker } from "@/components/ui/date-picker";
import { formatDateInputValue, parseDateInputValue } from "@/lib/utils/format";

type DateInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & {
  value: string | null | undefined;
  onChange: (value: string) => void;
  /** Ersetzt den Kalender, z. B. durch die Kalenderansicht mit Terminen. */
  onPickerClick?: () => void;
};

export function DateInput({
  value,
  onChange,
  className,
  disabled,
  readOnly,
  placeholder = "dd.mm.yyyy",
  onBlur,
  min,
  max,
  onPickerClick,
  ...props
}: DateInputProps) {
  const t = useTranslations("common");
  const [displayValue, setDisplayValue] = useState(() => formatDateInputValue(value));
  const textInputRef = useRef<HTMLInputElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const pickerButtonRef = useRef<HTMLButtonElement | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);

  useEffect(() => {
    setDisplayValue(formatDateInputValue(value));
  }, [value]);

  function commitValue(rawValue: string, input?: HTMLInputElement | null) {
    const targetInput = input ?? textInputRef.current;
    const trimmed = rawValue.trim();
    if (!trimmed) {
      if (targetInput) {
        targetInput.setCustomValidity("");
      }
      setDisplayValue("");
      onChange("");
      return;
    }

    const normalized = parseDateInputValue(trimmed);
    if (!normalized) {
      if (targetInput) {
        targetInput.setCustomValidity(t("dateField.invalidFormat"));
      }
      return;
    }

    if (targetInput) {
      targetInput.setCustomValidity("");
    }
    setDisplayValue(formatDateInputValue(normalized));
    onChange(normalized);
  }

  function handleBlur(event: FocusEvent<HTMLInputElement>) {
    commitValue(event.target.value, event.target);
    if (event.target.validationMessage) {
      event.target.reportValidity();
    }
    onBlur?.(event);
  }

  function openPicker() {
    if (disabled || readOnly) {
      return;
    }
    if (onPickerClick) {
      onPickerClick();
      return;
    }
    setCalendarOpen((current) => !current);
  }

  return (
    <div ref={wrapperRef} className={`date-input${className ? ` ${className}` : ""}`}>
      <input
        ref={textInputRef}
        {...props}
        type="text"
        value={displayValue}
        disabled={disabled}
        readOnly={readOnly}
        inputMode="numeric"
        autoComplete="off"
        placeholder={placeholder}
        className="date-input-field"
        onChange={(event) => {
          const rawValue = event.target.value;
          setDisplayValue(event.target.value);
          if (!rawValue.trim()) {
            event.target.setCustomValidity("");
            onChange("");
            return;
          }
          const normalized = parseDateInputValue(rawValue);
          if (normalized) {
            event.target.setCustomValidity("");
            onChange(normalized);
            return;
          }
          event.target.setCustomValidity(t("dateField.invalidFormat"));
        }}
        onBlur={handleBlur}
      />
      <button
        ref={pickerButtonRef}
        type="button"
        className="date-input-picker"
        onClick={openPicker}
        aria-haspopup="dialog"
        aria-expanded={onPickerClick ? undefined : calendarOpen}
        disabled={disabled || readOnly}
        aria-label={t("dateField.chooseDate")}
        title={t("dateField.chooseDate")}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="2.25" y="3.25" width="11.5" height="10.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M5 1.75v3M11 1.75v3M2.5 6h11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
      {calendarOpen && (
        <DatePicker
          anchorRef={wrapperRef}
          returnFocusRef={pickerButtonRef}
          value={parseDateInputValue(value) || null}
          min={min === undefined ? undefined : String(min)}
          max={max === undefined ? undefined : String(max)}
          onSelect={(selected) => commitValue(selected)}
          onClose={() => setCalendarOpen(false)}
        />
      )}
    </div>
  );
}
