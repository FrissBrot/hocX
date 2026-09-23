"use client";

import { useEffect, useRef, useState } from "react";

/** Verzögertes Autosave; Schliessen wartet auf alle noch ausstehenden Änderungen. */
export function useDeferredPopupSave() {
  const pending = useRef<(() => Promise<void>) | null>(null);
  const running = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function flush(): Promise<boolean> {
    if (timer.current) clearTimeout(timer.current);
    if (running.current) return running.current;
    const work = async () => {
      setSaving(true);
      setSaveError(null);
      try {
        while (pending.current) {
          const save = pending.current;
          pending.current = null;
          try { await save(); }
          catch (error) {
            pending.current ??= save;
            throw error;
          }
        }
        return true;
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "Änderungen konnten nicht gespeichert werden.");
        return false;
      } finally { setSaving(false); }
    };
    const promise = work();
    running.current = promise;
    try { return await promise; }
    finally { running.current = null; }
  }

  function schedule(save: () => Promise<void>) {
    pending.current = save;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void flush(); }, 500);
  }

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return { schedule, flush, saving, saveError };
}
