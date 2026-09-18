"use client";

import { useEffect, useRef } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { PhotoAnalysisProgress as ProgressData } from "@/types/api";

const POLL_INTERVAL_MS = 15000;

// Polls /api/files/analysis-progress while anything is still pending and reports the
// current summary up to the parent (for the "Analyse läuft · N Bilder" pill next to the
// page title) - headless, renders nothing itself.
export function PhotoAnalysisProgress({ onUpdate }: { onUpdate?: (progress: ProgressData | null) => void }) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const data = await browserApiFetch<ProgressData>("/api/files/analysis-progress");
        if (cancelled) return;
        onUpdateRef.current?.(data ?? null);
        if (data && data.pending_images > 0) {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch {
        // Transient - the next mount/manual refresh will try again; no error UI for a
        // background progress indicator.
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return null;
}
