"use client";

import { KeyboardEvent, useState } from "react";
import { useTranslations } from "next-intl";

type Props = {
  value: number | "";
  onChange: (value: number | "") => void;
  min: number;
  /** Ohne `max` nach oben offen */
  max?: number;
  /** Leeres Feld ist ein gültiger Wert (z. B. «sofort», «nie», «unbegrenzt») */
  allowEmpty?: boolean;
  /** «−» beim Minimum leert das Feld (nur mit `allowEmpty`, Standard: wie `allowEmpty`) */
  decrementToEmpty?: boolean;
  /** Bedeutung des leeren Feldes, für Screenreader und als Platzhalter */
  emptyLabel?: string;
  /** Kürzerer Platzhalter, wenn `emptyLabel` nicht ins Feld passt (z. B. «∞») */
  emptyPlaceholder?: string;
  /** Name des Feldes für Screenreader und die Beschriftung von «−»/«+» */
  label: string;
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  className?: string;
};

function clamp(value: number, min: number, max: number | undefined): number {
  return Math.max(min, max === undefined ? value : Math.min(max, value));
}

/** Ganzzahl mit «−»/«+» (Design «hocX Abgabe Felder v6»). Tippen geht frei, «−»/«+» und
 * Pfeil hoch/runter zählen; Werte ausserhalb von min/max werden auf die Grenze gesetzt. */
export function NumberStepper({
  value,
  onChange,
  min,
  max,
  allowEmpty = false,
  decrementToEmpty = allowEmpty,
  emptyLabel,
  emptyPlaceholder = emptyLabel,
  label,
  id,
  className,
  ...aria
}: Props) {
  const t = useTranslations("common.numberStepper");
  // Während des Tippens darf das Feld kurz leer oder unter dem Minimum sein
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value === "" ? "" : String(value));

  function step(direction: 1 | -1) {
    if (value === "") {
      if (direction === 1) onChange(min);
      return;
    }
    if (direction === -1 && value <= min) {
      if (allowEmpty && decrementToEmpty) onChange("");
      return;
    }
    onChange(clamp(value + direction, min, max));
  }

  function type(text: string) {
    const digits = text.replace(/[^0-9]/g, "");
    if (digits === "") {
      setDraft("");
      if (allowEmpty) onChange("");
      return;
    }
    const number = Number(digits);
    const capped = max === undefined ? number : Math.min(max, number);
    setDraft(String(capped));
    if (capped >= min) onChange(capped);
  }

  function commit() {
    if (draft !== null && draft !== "" && Number(draft) < min) onChange(min);
    else if (draft === "" && !allowEmpty && value === "") onChange(min);
    setDraft(null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      setDraft(null);
      step(event.key === "ArrowUp" ? 1 : -1);
    }
  }

  const canDecrease = value !== "" && (value > min || (allowEmpty && decrementToEmpty));
  const canIncrease = value === "" || max === undefined || value < max;

  return (
    <div className={className ? `number-stepper ${className}` : "number-stepper"}>
      <button type="button" className="number-stepper-button" tabIndex={-1} aria-label={t("decrease", { label })} disabled={!canDecrease} onClick={() => step(-1)}>
        −
      </button>
      <input
        id={id}
        className="number-stepper-input"
        type="text"
        inputMode="numeric"
        role="spinbutton"
        aria-label={label}
        aria-valuenow={value === "" ? undefined : value}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuetext={value === "" ? emptyLabel : undefined}
        placeholder={emptyPlaceholder}
        value={shown}
        onChange={(event) => type(event.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
        {...aria}
      />
      <button type="button" className="number-stepper-button" tabIndex={-1} aria-label={t("increase", { label })} disabled={!canIncrease} onClick={() => step(1)}>
        +
      </button>
    </div>
  );
}
