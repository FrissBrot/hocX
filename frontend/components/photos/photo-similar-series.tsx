"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatTime } from "@/lib/utils/format";
import { FileBulkDeleteResult, FileOverviewItem, SimilarityGroup } from "@/types/api";
import { PhotoViewer, ViewerPermissions } from "./photo-viewer";
import { SimilarityComputedAt, SimilarityState } from "./similarity-state";
import { markSimilarityGroupReviewed, useReviewedSimilarityGroups, useSimilarityGroups } from "./use-similarity-groups";
import { groupKey } from "./viewer/viewer-logic";

export function PhotoSimilarSeries({
  search,
  tagFilter,
  onDeleted,
  viewerPermissions,
}: {
  search: string;
  tagFilter: string[];
  onDeleted?: (deletedIds: string[]) => void;
  viewerPermissions?: ViewerPermissions;
}) {
  const t = useTranslations("photos.similarSeries");
  const confirm = useConfirm();
  const showToast = useToast();
  const { groups, setGroups, status, computedAt, error } = useSimilarityGroups("duplicate", search, tagFilter, t("loadError"));
  // «Geprüft» gilt für die Sitzung und ist mit der Foto-Ansicht geteilt (Vergleichsmodus).
  const reviewed = useReviewedSimilarityGroups();
  const [busyGroup, setBusyGroup] = useState<string | null>(null);
  const [viewer, setViewer] = useState<{ groupId: string; index: number } | null>(null);

  function keepSeries(group: SimilarityGroup) {
    markSimilarityGroupReviewed(groupKey("duplicate", group));
  }

  function updateImage(id: string, changes: Partial<FileOverviewItem>) {
    setGroups((current) => current?.map((group) => ({
      ...group,
      images: group.images.map((image) => image.id === id ? { ...image, ...changes } : image),
    })) ?? null);
  }

  async function toggleBest(image: FileOverviewItem) {
    const isBest = !image.is_best;
    try {
      await browserApiFetch(`/api/files/${image.id}/best`, {
        method: "PATCH",
        body: JSON.stringify({ best_override: isBest ? "include" : "exclude" }),
      });
      updateImage(image.id, { is_best: isBest });
    } catch {
      showToast(t("bestError"), "error");
    }
  }

  async function keepOnlyBest(group: SimilarityGroup) {
    const rest = group.images.filter((image) => image.id !== group.best_id);
    if (rest.length === 0 || busyGroup) return;
    const ok = await confirm({
      tone: "danger",
      message: t("deleteConfirm", { count: rest.length }),
    });
    if (!ok) return;
    setBusyGroup(group.best_id);
    try {
      const result = await browserApiFetch<FileBulkDeleteResult>("/api/files/bulk-delete", {
        method: "POST",
        body: JSON.stringify({ file_ids: rest.map((image) => image.id) }),
      });
      markSimilarityGroupReviewed(groupKey("duplicate", group));
      const deletedCount = result?.deleted_ids.length ?? 0;
      if (result && deletedCount > 0) {
        // Auch aus dem Cache entfernen - sonst kehrt die Gruppe beim nächsten Tabwechsel zurück.
        const deletedSet = new Set(result.deleted_ids);
        setGroups((current) => current
          ?.map((entry) => ({ ...entry, images: entry.images.filter((image) => !deletedSet.has(image.id)) }))
          .filter((entry) => entry.images.length >= 2) ?? null);
        onDeleted?.(result.deleted_ids);
      }
      if (result?.errors.length) {
        showToast(result.errors.join(" · "), deletedCount > 0 ? "info" : "error");
      } else {
        showToast(t("cleanedToast"), "success");
      }
    } catch {
      showToast(t("cleanError"), "error");
    } finally {
      setBusyGroup(null);
    }
  }

  if (!groups) return <SimilarityState status={status} error={error} loading={t("loading")} />;

  const visible = groups.filter((group) => !reviewed.has(groupKey("duplicate", group)));
  const viewerGroup = visible.find((group) => group.best_id === viewer?.groupId);

  return (
    <div className="grid">
      <p className="muted">
        {t("intro")}
      </p>
      <SimilarityComputedAt computedAt={computedAt} />
      {visible.length === 0 ? (
        <p className="muted">{t("empty")}</p>
      ) : (
        visible.map((group) => {
          const best = group.images.find((image) => image.id === group.best_id) ?? group.images[0];
          const description = best.albums[0]?.name ?? best.context_label ?? best.original_name;
          const deletableCount = group.images.filter((image) => image.id !== group.best_id && image.source === "gallery_upload").length;
          const otherCount = group.images.length - 1;
          return (
            <div key={group.best_id} className="photo-series-card">
              <div className="photo-series-header">
                <div>
                  <span className="photo-series-title">{t("seriesTitle", { time: formatTime(best.created_at), description })}</span>
                  <span className="photo-series-count muted"> {t("similarCount", { count: group.images.length })}</span>
                </div>
                <div className="photo-series-actions">
                  <button type="button" className="button-ghost button-secondary" onClick={() => keepSeries(group)} disabled={busyGroup === group.best_id}>
                    {t("keepSeries")}
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void keepOnlyBest(group)}
                    disabled={busyGroup === group.best_id || deletableCount === 0}
                    title={deletableCount === 0 ? t("keepOnlyBestDisabledTitle") : undefined}
                  >
                    {t("keepOnlyBest")}
                  </button>
                </div>
              </div>
              {deletableCount < otherCount && deletableCount > 0 && (
                <p className="muted photo-series-hint">{t("skippedHint")}</p>
              )}
              <div className="photo-series-strip">
                {group.images.map((image, index) => {
                  const isBest = image.id === group.best_id;
                  const thumbnailUrl = image.thumbnail_url ? `${browserApiBaseUrl}${image.thumbnail_url}` : `${browserApiBaseUrl}${image.content_url}`;
                  return (
                    <div key={image.id} className={`photo-series-item${isBest ? " photo-series-item-best" : ""}`}>
                      <button
                        type="button"
                        className="photo-series-thumb-wrap"
                        aria-label={t("openAriaLabel", { name: image.original_name })}
                        onClick={() => setViewer({ groupId: group.best_id, index })}
                      >
                        <img src={thumbnailUrl} alt={image.original_name} loading="lazy" decoding="async" draggable={false} />
                        {isBest && <span className="photo-series-badge">{t("bestChoice")}</span>}
                      </button>
                      <span className="photo-series-caption muted">
                        {t("sharpnessCaption", { score: image.sharpness_score !== null ? image.sharpness_score.toFixed(1) : "–" })}
                        {isBest ? t("bestSuffix") : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
      {viewer && viewerGroup && viewerGroup.images[viewer.index] && (
        <PhotoViewer
          items={viewerGroup.images}
          index={viewer.index}
          onIndexChange={(index) => setViewer({ groupId: viewer.groupId, index })}
          onClose={() => setViewer(null)}
          onToggleBest={toggleBest}
          onTagsSaved={(id, tags) => updateImage(id, { tags })}
          {...viewerPermissions}
          onRemoved={(ids, nextId) => {
            onDeleted?.(ids);
            const rest = viewerGroup.images.filter((image) => !ids.includes(image.id));
            const nextIndex = nextId ? rest.findIndex((image) => image.id === nextId) : -1;
            setViewer(rest.length < 2 ? null : { groupId: viewer.groupId, index: nextIndex >= 0 ? nextIndex : Math.min(viewer.index, rest.length - 1) });
          }}
        />
      )}
    </div>
  );
}
