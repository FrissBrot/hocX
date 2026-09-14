"use client";

import { useEffect, useRef, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { PhotoAnalysisProgress as ProgressData } from "@/types/api";

const POLL_INTERVAL_MS = 15000;

// Polls /api/files/analysis-progress while anything is still pending and reports the
// current summary up to the parent (for the "Analyse läuft · N Bilder" pill next to the
// page title) - renders the progress bar itself only while pending_images > 0.
export function PhotoAnalysisProgress({ onUpdate }: { onUpdate?: (progress: ProgressData | null) => void }) {
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const data = await browserApiFetch<ProgressData>("/api/files/analysis-progress");
        if (cancelled) return;
        setProgress(data);
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

  if (!progress || progress.pending_images === 0) return null;

  const percent = progress.total_images > 0 ? Math.round((progress.analyzed_images / progress.total_images) * 100) : 0;

  return (
    <div className="photo-analysis-progress">
      <span className="photo-analysis-progress-label muted">
        Foto-Analyse läuft – {progress.analyzed_images} von {progress.total_images} Bildern bewertet (Schärfe, Belichtung, Gesichtsqualität)
      </span>
      <div className="photo-analysis-bar">
        <div className="photo-analysis-bar-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
