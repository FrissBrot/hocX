"use client";

import { useTranslations } from "next-intl";

import { PASSWORD_MIN_LENGTH, PasswordStrength, passwordStrengthLevel } from "@/lib/password-strength";

const SEGMENTS = [0, 1, 2, 3];

/**
 * Live-Stärke unter dem Passwortfeld: vier Segmente, Stufe, Checkliste und Hinweis. Die Regel selbst
 * (lib/password-strength.ts) prüft das Backend beim Speichern noch einmal.
 */
export function PasswordStrengthMeter({ strength }: { strength: PasswordStrength }) {
  const t = useTranslations("auth.setPassword");
  const level = passwordStrengthLevel(strength);
  const filled = level === "empty" ? 0 : level === "tooShort" ? 1 : Math.max(strength.score, 1);
  const checks = [
    { key: "minLength", ok: strength.checks.minLength, label: t("checks.minLength", { count: PASSWORD_MIN_LENGTH }) },
    { key: "mixedCase", ok: strength.checks.mixedCase, label: t("checks.mixedCase") },
    { key: "numberOrSymbol", ok: strength.checks.numberOrSymbol, label: t("checks.numberOrSymbol") },
    { key: "notGuessable", ok: strength.checks.notGuessable, label: t("checks.notGuessable") },
  ];
  const hint = strength.guessable
    ? { text: t("hints.guessable"), bad: true }
    : level === "weak"
      ? { text: t("hints.tooWeak"), bad: true }
      : level === "medium"
        ? { text: t("hints.medium"), bad: false }
        : null;

  return (
    <div className={`pw-strength pw-strength-${level}`}>
      <div className="pw-strength-bar-row">
        <div className="pw-strength-bar" aria-hidden="true">
          {SEGMENTS.map((index) => (
            <span key={index} className={index < filled ? "pw-strength-segment is-filled" : "pw-strength-segment"} />
          ))}
        </div>
        <span className="pw-strength-label" aria-live="polite">
          {level === "empty" ? "" : t(`strength.${level}`)}
        </span>
      </div>
      <ul className="pw-strength-checks">
        {checks.map((check) => (
          <li key={check.key} className={check.ok ? "pw-strength-check is-ok" : "pw-strength-check"}>
            <span className="pw-strength-check-mark" aria-hidden="true">{check.ok ? "✓" : "·"}</span>
            <span>{check.label}</span>
            <span className="pw-sr-only">{check.ok ? t("checks.met") : t("checks.notMet")}</span>
          </li>
        ))}
      </ul>
      {hint ? <p className={hint.bad ? "pw-strength-hint is-bad" : "pw-strength-hint"}>{hint.text}</p> : null}
    </div>
  );
}
