"use client";

import { FocusEvent, InputHTMLAttributes, useEffect, useRef, useState } from "react";

import { formatDateInputValue, parseDateInputValue } from "@/lib/utils/format";

type DateInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & {
  value: string | null | undefined;
  onChange: (value: string) => void;
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
  ...props
}: DateInputProps) {
  const [displayValue, setDisplayValue] = useState(() => formatDateInputValue(value));
  const textInputRef = useRef<HTMLInputElement | null>(null);
  const nativeInputRef = useRef<HTMLInputElement | null>(null);

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
        targetInput.setCustomValidity("Bitte Datum als TT.MM.JJJJ eingeben");
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

  function openNativePicker() {
    if (disabled || readOnly) {
      return;
    }
    if (nativeInputRef.current && typeof nativeInputRef.current.showPicker === "function") {
      nativeInputRef.current.showPicker();
      return;
    }
    nativeInputRef.current?.focus();
    nativeInputRef.current?.click();
  }

  return (
    <div className={`date-input${className ? ` ${className}` : ""}`}>
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
          event.target.setCustomValidity("Bitte Datum als TT.MM.JJJJ eingeben");
        }}
        onBlur={handleBlur}
      />
      <button
        type="button"
        className="date-input-picker"
        onClick={openNativePicker}
        disabled={disabled || readOnly}
        aria-label="Datum waehlen"
        title="Datum waehlen"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="2.25" y="3.25" width="11.5" height="10.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M5 1.75v3M11 1.75v3M2.5 6h11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>
      <input
        ref={nativeInputRef}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        className="date-input-native"
        value={parseDateInputValue(value) || ""}
        onChange={(event) => commitValue(event.target.value)}
        min={min}
        max={max}
        disabled={disabled}
      />
    </div>
  );
}
