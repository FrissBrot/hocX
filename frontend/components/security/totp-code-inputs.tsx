"use client";

import { ChangeEvent, ClipboardEvent, KeyboardEvent, useMemo, useRef } from "react";

export const TOTP_CODE_LENGTH = 6;

export function sanitizeTotpCode(value: string): string {
  return value.replace(/\D/g, "").slice(0, TOTP_CODE_LENGTH);
}

type Props = {
  code: string;
  onChange: (code: string) => void;
  /** Beschriftung je Feld für Screenreader, z. B. t("mfa.codeDigitLabel", { n }) */
  digitLabel: (n: number) => string;
  disabled?: boolean;
  autoFocus?: boolean;
};

/**
 * Sechs Ziffernfelder für einen TOTP-Code (Optik `.mfa-code-input` aus styles/login.css, wie im
 * Login): Tippen springt weiter, Rücktaste zurück, Einfügen verteilt den ganzen Code.
 */
export function TotpCodeInputs({ code, onChange, digitLabel, disabled = false, autoFocus = false }: Props) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = useMemo(() => Array.from({ length: TOTP_CODE_LENGTH }, (_, index) => code[index] ?? ""), [code]);

  function focus(index: number) {
    requestAnimationFrame(() => {
      refs.current[index]?.focus();
      refs.current[index]?.select();
    });
  }

  function setDigits(index: number, value: string) {
    const entered = sanitizeTotpCode(value);
    const next = [...digits];
    if (!entered) {
      next[index] = "";
      onChange(next.join(""));
      return;
    }
    entered.split("").forEach((digit, offset) => {
      if (index + offset < TOTP_CODE_LENGTH) next[index + offset] = digit;
    });
    onChange(next.join(""));
    focus(Math.min(index + entered.length, TOTP_CODE_LENGTH - 1));
  }

  function handleKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace") {
      event.preventDefault();
      const next = [...digits];
      if (next[index]) {
        next[index] = "";
      } else if (index > 0) {
        next[index - 1] = "";
        focus(index - 1);
      }
      onChange(next.join(""));
    } else if (event.key === "ArrowLeft" && index > 0) {
      event.preventDefault();
      focus(index - 1);
    } else if (event.key === "ArrowRight" && index < TOTP_CODE_LENGTH - 1) {
      event.preventDefault();
      focus(index + 1);
    }
  }

  function handlePaste(index: number, event: ClipboardEvent<HTMLInputElement>) {
    const pasted = sanitizeTotpCode(event.clipboardData.getData("text"));
    if (!pasted) return;
    event.preventDefault();
    setDigits(index, pasted);
  }

  return (
    <div className="mfa-code-inputs">
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(node) => {
            refs.current[index] = node;
          }}
          className="mfa-code-input"
          value={digit}
          onChange={(event: ChangeEvent<HTMLInputElement>) => setDigits(index, event.target.value)}
          onKeyDown={(event) => handleKeyDown(index, event)}
          onPaste={(event) => handlePaste(index, event)}
          onFocus={(event) => event.currentTarget.select()}
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          aria-label={digitLabel(index + 1)}
          disabled={disabled}
          autoFocus={autoFocus && index === 0}
        />
      ))}
    </div>
  );
}
