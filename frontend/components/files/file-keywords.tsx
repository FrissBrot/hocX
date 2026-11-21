"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { KeywordInput } from "@/components/ui/keyword-input";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";

export type StoredFileKeywords = { keywords: string[]; can_edit: boolean };

/**
 * Keywords einer Datei oder eines Fotos (nur für die Suche, «weniger verbindlich als Tags").
 * Eigenständig: lädt und speichert selbst über /api/stored-files/{id}/keywords, damit Datei-Detail
 * und Foto-Ansicht sie mit einer Zeile einhängen können. Ohne Leserecht (Fehler beim Laden)
 * erscheint nichts; ohne Schreibrecht nur lesend und nur, wenn es Keywords gibt.
 */
export function FileKeywords({
  fileId,
  readOnly = false,
  className,
  titleClassName,
}: {
  fileId: string;
  /** Zusätzlich gesperrt (z. B. Datei im Papierkorb). */
  readOnly?: boolean;
  /** Klasse des umgebenden Abschnitts (z. B. der Abschnittsrahmen von Datei-Detail oder Foto-Ansicht). */
  className?: string;
  /** Klasse der Abschnittsüberschrift im jeweiligen Rahmen. */
  titleClassName?: string;
}) {
  const t = useTranslations("files.keywords");
  // Fehler inline statt Toast: der Baustein soll ohne Provider in jedem Rahmen laufen
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<StoredFileKeywords | null>(null);
  const [saving, setSaving] = useState(false);
  // Nur die jüngste Speicherung zählt (schnelles Tippen, Blättern)
  const saveIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setState(null);
    setError(null);
    Promise.resolve()
      .then(() => browserApiFetch<StoredFileKeywords>(`/api/stored-files/${fileId}/keywords`))
      // Nur eine gültige Antwort zeigt den Abschnitt (fremde/unerwartete Antwort: nichts anzeigen)
      .then((data) => { if (!cancelled) setState(data && Array.isArray(data.keywords) ? data : null); })
      .catch(() => { if (!cancelled) setState(null); });
    return () => {
      cancelled = true;
    };
  }, [fileId]);

  if (!state) return null;
  const editable = state.can_edit && !readOnly;
  if (!editable && state.keywords.length === 0) return null;

  async function save(next: string[]) {
    const previous = state;
    const saveId = ++saveIdRef.current;
    setState((current) => (current ? { ...current, keywords: next } : current));
    setSaving(true);
    setError(null);
    try {
      const saved = await browserApiFetch<StoredFileKeywords>(`/api/stored-files/${fileId}/keywords`, {
        method: "PATCH",
        body: JSON.stringify({ keywords: next }),
      });
      if (saved && Array.isArray(saved.keywords) && saveId === saveIdRef.current) setState(saved);
    } catch (failure) {
      if (saveId === saveIdRef.current) {
        setState(previous);
        setError(failure instanceof Error && failure.message ? failure.message : t("saveError"));
      }
    } finally {
      if (saveId === saveIdRef.current) setSaving(false);
    }
  }

  return (
    <section className={`file-keywords${className ? ` ${className}` : ""}`} data-testid="file-keywords">
      <div className={titleClassName}>
        {t("title")} {saving ? <span className="muted">{t("saving")}</span> : null}
      </div>
      <KeywordInput
        value={state.keywords}
        onChange={(next) => void save(next)}
        label={t("inputLabel")}
        placeholder={t("placeholder")}
        readOnly={!editable}
      />
      {error ? <StatusBanner tone="error" message={error} /> : null}
      <p className="keyword-section-hint">{t("hint")}</p>
    </section>
  );
}
