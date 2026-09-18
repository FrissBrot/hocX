"use client";

import { useEffect, useRef, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { GalleryUploadJob, GalleryUploadJobDetail } from "@/types/api";

const POLL_INTERVAL_MS = 3000;

// Polls /api/files/gallery-upload-jobs (tenant-wide, like PhotoAnalysisProgress polls
// analysis-progress - so the bar shows up for any writer in the tenant, any tab, after a
// refresh, not just whoever's browser sent the original upload request) while at least one
// job is queued/running, and renders a bar only then. A job that leaves this "active" list
// has finished (done or failed) - tracked via previouslyActiveRef so each one is reported
// to the parent exactly once, via a follow-up fetch of its full result.
export function GalleryUploadProgress({ onJobDone }: { onJobDone?: (job: GalleryUploadJobDetail) => void }) {
  const [activeJobs, setActiveJobs] = useState<GalleryUploadJob[]>([]);
  const previouslyActiveRef = useRef<Set<string>>(new Set());
  const onJobDoneRef = useRef(onJobDone);
  onJobDoneRef.current = onJobDone;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const jobs = (await browserApiFetch<GalleryUploadJob[]>("/api/files/gallery-upload-jobs")) ?? [];
        if (cancelled) return;

        const stillActiveIds = new Set(jobs.map((job) => job.id));
        for (const id of previouslyActiveRef.current) {
          if (stillActiveIds.has(id)) continue;
          browserApiFetch<GalleryUploadJobDetail>(`/api/files/gallery-upload-jobs/${id}`)
            .then((detail) => {
              if (detail) onJobDoneRef.current?.(detail);
            })
            .catch(() => {
              // Transient - the job already left the active list either way, nothing more
              // to poll for it.
            });
        }
        previouslyActiveRef.current = stillActiveIds;

        setActiveJobs(jobs);
        if (jobs.length > 0) {
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

  if (activeJobs.length === 0) return null;

  const processed = activeJobs.reduce((sum, job) => sum + job.processed_files, 0);
  const knownTotal = activeJobs.every((job) => job.total_files !== null)
    ? activeJobs.reduce((sum, job) => sum + (job.total_files ?? 0), 0)
    : null;
  const percent = knownTotal && knownTotal > 0 ? Math.round((processed / knownTotal) * 100) : null;

  return (
    <div className="photo-analysis-progress">
      <span className="photo-analysis-progress-label muted">
        {knownTotal !== null
          ? `Galerie-Upload läuft – ${processed} von ${knownTotal} Bildern verarbeitet`
          : `Galerie-Upload läuft – ${processed} Bilder verarbeitet…`}
      </span>
      <div className="photo-analysis-bar">
        <div className="photo-analysis-bar-fill" style={{ width: `${percent ?? 30}%` }} />
      </div>
    </div>
  );
}
