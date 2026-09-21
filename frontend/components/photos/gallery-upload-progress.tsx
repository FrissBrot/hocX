"use client";

import { useEffect, useRef } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { GalleryUploadJob, GalleryUploadJobDetail } from "@/types/api";

const POLL_INTERVAL_MS = 3000;

// Polls /api/files/gallery-upload-jobs (tenant-wide, like PhotoAnalysisProgress polls
// analysis-progress - so the pill shows up for any writer in the tenant, any tab, after a
// refresh, not just whoever's browser sent the original upload request) while at least one
// job is queued/running. Headless, like PhotoAnalysisProgress - reports the active jobs up
// via onUpdate for the parent's own "Galerie-Upload läuft" pill, renders nothing itself. A
// job that leaves this "active" list has finished (done or failed) - tracked via
// previouslyActiveRef so each one is reported to the parent exactly once, via a follow-up
// fetch of its full result.
export function GalleryUploadProgress({
  onUpdate,
  onJobDone,
  queuedJobId,
}: {
  queuedJobId?: string;
  onUpdate?: (jobs: GalleryUploadJob[]) => void;
  onJobDone?: (job: GalleryUploadJobDetail) => void;
}) {
  const previouslyActiveRef = useRef<Set<string>>(new Set());
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;
  const onJobDoneRef = useRef(onJobDone);
  onJobDoneRef.current = onJobDone;

  useEffect(() => {
    if (queuedJobId) previouslyActiveRef.current.add(queuedJobId);
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

        onUpdateRef.current?.(jobs);
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
  }, [queuedJobId]);

  return null;
}
