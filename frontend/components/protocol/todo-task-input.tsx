"use client";

import { useEffect, useRef, useState } from "react";

const SAVE_DELAY_MS = 600;

/**
 * Text einer Pendenz mit lokalem Entwurf: Tippen ändert nur dieses Feld, gespeichert wird nach
 * einer kurzen Pause oder beim Verlassen des Felds. Vorher lief pro Taste ein PATCH, dessen
 * Antwort den ganzen Editor (und bei allen Verbundenen das Dokument) neu renderte.
 * Solange der Entwurf ungespeichert ist, überschreibt ein eintreffender Stand (eigene Antwort,
 * Änderung einer anderen Person) den Text nicht.
 */
export function TodoTaskInput({
  value,
  className,
  readOnly,
  onSave,
  onResize,
}: {
  value: string;
  className: string;
  readOnly: boolean;
  onSave: (task: string) => void;
  onResize: (target: HTMLTextAreaElement) => void;
}) {
  const [draft, setDraft] = useState(value);
  const dirtyRef = useRef(false);
  const timerRef = useRef<number | undefined>(undefined);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;

  useEffect(() => {
    if (!dirtyRef.current) setDraft(value);
  }, [value]);

  function flush() {
    window.clearTimeout(timerRef.current);
    timerRef.current = undefined;
    if (!dirtyRef.current) return;
    dirtyRef.current = false;
    onSaveRef.current(draftRef.current);
  }

  // Beim Entfernen (Punkt gewechselt, Pendenz gelöscht) nichts verlieren.
  useEffect(() => () => flush(), []);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <textarea
      className={className}
      rows={1}
      value={draft}
      readOnly={readOnly}
      onInput={(event) => onResize(event.currentTarget)}
      onChange={(event) => {
        if (readOnly) return;
        setDraft(event.target.value);
        dirtyRef.current = true;
        window.clearTimeout(timerRef.current);
        timerRef.current = window.setTimeout(flush, SAVE_DELAY_MS);
      }}
      onBlur={flush}
    />
  );
}
