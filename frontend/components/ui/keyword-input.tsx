"use client";

import { useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";

/** Trennt eine Eingabe/Einfügung an Komma, Semikolon und Zeilenumbruch in Begriffe. */
export function splitKeywords(value: string): string[] {
  return value
    .split(/[,;\n]+/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

/** Fügt Begriffe an (ohne Duplikate, Gross-/Kleinschreibung egal), Reihenfolge bleibt. */
export function mergeKeywords(current: string[], added: string[]): string[] {
  const seen = new Set(current.map((keyword) => keyword.toLocaleLowerCase()));
  const next = [...current];
  for (const keyword of added) {
    const key = keyword.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    next.push(keyword);
  }
  return next;
}

/**
 * Liste kurzer Begriffe (Keywords, Synonyme): schlichte Chips ohne Farbe, ein Textfeld.
 * Tastatur: Enter oder Komma übernimmt den Begriff, Rücktaste im leeren Feld entfernt den letzten,
 * jeder Chip hat einen eigenen Entfernen-Knopf (Tab erreichbar). Verlassen des Felds übernimmt
 * angefangenen Text. Einfügen trennt an Komma/Semikolon/Zeilenumbruch.
 */
export function KeywordInput({
  value,
  onChange,
  label,
  placeholder,
  readOnly = false,
  maxLength = 40,
  className,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  /** Zugänglicher Name des Textfelds (sichtbares Label liefert der Aufrufer). */
  label: string;
  placeholder?: string;
  readOnly?: boolean;
  maxLength?: number;
  className?: string;
}) {
  const t = useTranslations("common.keywordInput");
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  function commit(text: string) {
    const parts = splitKeywords(text).map((part) => part.slice(0, maxLength));
    setDraft("");
    if (parts.length === 0) return;
    const next = mergeKeywords(value, parts);
    if (next.length !== value.length) onChange(next);
  }

  function remove(keyword: string) {
    onChange(value.filter((entry) => entry !== keyword));
    inputRef.current?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if ((event.key === "Enter" || event.key === ",") && draft.trim()) {
      event.preventDefault();
      commit(draft);
    } else if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
    } else if (event.key === "Backspace" && !draft && value.length > 0) {
      event.preventDefault();
      onChange(value.slice(0, -1));
    }
  }

  function handlePaste(event: React.ClipboardEvent<HTMLInputElement>) {
    const text = event.clipboardData.getData("text");
    if (!/[,;\n]/.test(text)) return;
    event.preventDefault();
    commit(`${draft}${text}`);
  }

  return (
    <div className={`tag-input-field keyword-input${readOnly ? " keyword-input-readonly" : ""}${className ? ` ${className}` : ""}`}>
      {value.length > 0 ? (
        <ul className="keyword-input-list" id={listId} aria-label={label}>
          {value.map((keyword) => (
            <li key={keyword} className="keyword-chip">
              <span className="keyword-chip-text">{keyword}</span>
              {readOnly ? null : (
                <button
                  type="button"
                  className="tag-chip-remove keyword-chip-remove"
                  aria-label={t("remove", { keyword })}
                  title={t("remove", { keyword })}
                  onClick={() => remove(keyword)}
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {readOnly ? (
        value.length === 0 ? <span className="muted keyword-input-empty">{t("empty")}</span> : null
      ) : (
        <input
          ref={inputRef}
          className="tag-input-text keyword-input-text"
          value={draft}
          maxLength={maxLength * 4}
          aria-label={label}
          aria-describedby={value.length > 0 ? listId : undefined}
          placeholder={placeholder ?? t("placeholder")}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onBlur={() => {
            if (draft.trim()) commit(draft);
          }}
        />
      )}
    </div>
  );
}
