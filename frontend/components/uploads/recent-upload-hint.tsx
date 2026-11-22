"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { PhotoActionIcon } from "@/components/photos/photo-action-icon";
import { browserApiFetch } from "@/lib/api/client";
import { dismissUploadHint, isUploadHintDismissed } from "@/lib/uploads/upload-jobs";
import type { UploadChannel, UploadJob, UploadJobList } from "@/types/api";

const RECENT_MS = 24 * 60 * 60 * 1000;

/** Hinweisstreifen oben auf Fotos/Ablage: eigener Upload der letzten 24 h - «48 Fotos hochgeladen –
 * bearbeiten». Pro Vorgang ausblendbar (localStorage); erscheint nur für eigene, abgeschlossene Vorgänge. */
export function RecentUploadHint({ channels, basePath, noun }: { channels: UploadChannel[]; basePath: string; noun: "photos" | "files" }) {
  const t = useTranslations("uploads.hint");
  const [job, setJob] = useState<UploadJob | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ mine: "true", limit: "5" });
    channels.forEach((channel) => params.append("channel", channel));
    browserApiFetch<UploadJobList>(`/api/upload-jobs?${params.toString()}`)
      .then((list) => {
        if (cancelled) return;
        const recent = (list?.items ?? []).find(
          (candidate) =>
            ["done", "partial"].includes(candidate.status) &&
            candidate.counts.uploaded > 0 &&
            Date.now() - new Date(candidate.created_at).getTime() < RECENT_MS &&
            !isUploadHintDismissed(candidate.id),
        );
        setJob(recent ?? null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels.join(",")]);

  if (!job) return null;
  return (
    <div className="upload-hint" role="status">
      <span className="upload-hint-text">{t(noun === "photos" ? "photos" : "files", { count: job.counts.uploaded })}</span>
      <Link className="upload-hint-link" href={`${basePath}/${job.id}`}>{t("edit")}</Link>
      <button
        type="button"
        className="button-icon-soft button-icon-soft-sm"
        aria-label={t("dismiss")}
        onClick={() => {
          dismissUploadHint(job.id);
          setJob(null);
        }}
      >
        <PhotoActionIcon name="close" />
      </button>
    </div>
  );
}
