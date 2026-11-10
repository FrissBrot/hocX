"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatTime } from "@/lib/utils/format";
import { FileBulkDeleteResult, FileOverviewItem, SimilarityGroup } from "@/types/api";
import { PhotoViewer } from "./photo-viewer";
import { SimilarityComputedAt, SimilarityState } from "./similarity-state";
import { useSimilarityGroups } from "./use-similarity-groups";

export function PhotoSimilarGroups({
  search,
  tagFilter,
  onDeleted,
}: {
  search: string;
  tagFilter: string[];
  onDeleted?: (deletedIds: string[]) => void;
}) {
  const t = useTranslations("photos.similarGroups");
  const confirm = useConfirm();
  const showToast = useToast();
  const { groups, setGroups, status, computedAt, error } = useSimilarityGroups("series", search, tagFilter, t("loadError"));
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // Which images stay when a group's selection is deleted - one Set per group (keyed by
  // best_id), seeded with just the best image once, then left to the user to extend. Deleting
  // never touches this set beyond removing gone ids - it's not re-seeded on every render, so a
  // group a user has already curated keeps its choices even as its `images` shrink.
  const [keepIds, setKeepIds] = useState<Record<string, Set<string>>>({});
  const [busyGroup, setBusyGroup] = useState<string | null>(null);
  const [viewer, setViewer] = useState<{ groupId: string; index: number } | null>(null);

  // Jede Gruppe startet mit dem besten Bild als "behalten"; schon getroffene Auswahlen
  // bleiben stehen, auch wenn die Gruppen im Hintergrund aktualisiert werden.
  useEffect(() => {
    if (!groups) return;
    setKeepIds((current) => {
      const missing = groups.filter((group) => !current[group.best_id]);
      if (missing.length === 0) return current;
      return { ...current, ...Object.fromEntries(missing.map((group) => [group.best_id, new Set([group.best_id])])) };
    });
  }, [groups]);

  function dismissGroup(group: SimilarityGroup) {
    setDismissed((current) => new Set(current).add(group.best_id));
  }

  function toggleKeep(groupId: string, imageId: string) {
    setKeepIds((current) => {
      const set = new Set(current[groupId] ?? [imageId]);
      if (set.has(imageId)) {
        if (set.size <= 1) return current; // mindestens ein Bild muss behalten bleiben
        set.delete(imageId);
      } else {
        set.add(imageId);
      }
      return { ...current, [groupId]: set };
    });
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

  async function deleteSelection(group: SimilarityGroup) {
    const kept = keepIds[group.best_id] ?? new Set([group.best_id]);
    const candidates = group.images.filter((image) => !kept.has(image.id));
    const deletable = candidates.filter((image) => image.source === "gallery_upload");
    if (deletable.length === 0 || busyGroup) return;
    const ok = await confirm({
      tone: "danger",
      message: t("deleteConfirm", { count: deletable.length }),
    });
    if (!ok) return;
    setBusyGroup(group.best_id);
    try {
      const result = await browserApiFetch<FileBulkDeleteResult>("/api/files/bulk-delete", {
        method: "POST",
        body: JSON.stringify({ file_ids: deletable.map((image) => image.id) }),
      });
      const deletedIds = result?.deleted_ids ?? [];
      // Anders als im Duplikate-Tab: die Gruppe bleibt sichtbar, nur die gelöschten Bilder
      // fallen aus ihrer Bilderliste - sie soll nicht verschwinden, nur weil etwas aus ihr
      // gelöscht wurde.
      if (deletedIds.length > 0) {
        const deletedSet = new Set(deletedIds);
        setGroups((current) => current?.map((current_group) => current_group.best_id === group.best_id
          ? { ...current_group, images: current_group.images.filter((image) => !deletedSet.has(image.id)) }
          : current_group) ?? null);
        onDeleted?.(deletedIds);
      }
      if (result?.errors.length) {
        showToast(result.errors.join(" · "), deletedIds.length > 0 ? "info" : "error");
      } else {
        showToast(t("deletedToast"), "success");
      }
    } catch {
      showToast(t("deleteError"), "error");
    } finally {
      setBusyGroup(null);
    }
  }

  if (!groups) return <SimilarityState status={status} error={error} loading={t("loading")} />;

  const visible = groups.filter((group) => !dismissed.has(group.best_id));
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
          const kept = keepIds[group.best_id] ?? new Set([group.best_id]);
          const nonKept = group.images.filter((image) => !kept.has(image.id));
          const deletableCount = nonKept.filter((image) => image.source === "gallery_upload").length;
          return (
            <div key={group.best_id} className="photo-series-card">
              <div className="photo-series-header">
                <div>
                  <span className="photo-series-title">{t("seriesTitle", { time: formatTime(best.created_at), description })}</span>
                  <span className="photo-series-count muted"> {t("similarCount", { count: group.images.length })}</span>
                </div>
                <div className="photo-series-actions">
                  <button type="button" className="button-ghost button-secondary" onClick={() => dismissGroup(group)} disabled={busyGroup === group.best_id}>
                    {t("hideSeries")}
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void deleteSelection(group)}
                    disabled={busyGroup === group.best_id || deletableCount === 0}
                    title={deletableCount === 0 ? t("deleteDisabledTitle") : undefined}
                  >
                    {t("deleteSelection")}
                  </button>
                </div>
              </div>
              {deletableCount < nonKept.length && deletableCount > 0 && (
                <p className="muted photo-series-hint">{t("skippedHint")}</p>
              )}
              <div className="photo-series-strip">
                {group.images.map((image, index) => {
                  const isBest = image.id === group.best_id;
                  const isKept = kept.has(image.id);
                  const thumbnailUrl = image.thumbnail_url ? `${browserApiBaseUrl}${image.thumbnail_url}` : `${browserApiBaseUrl}${image.content_url}`;
                  return (
                    <div key={image.id} className={`photo-series-item${isBest ? " photo-series-item-best" : ""}`}>
                      <div className="photo-series-thumb-wrap">
                        <button
                          type="button"
                          className="photo-series-thumb-open"
                          aria-label={t("openAriaLabel", { name: image.original_name })}
                          onClick={() => setViewer({ groupId: group.best_id, index })}
                        >
                          <img src={thumbnailUrl} alt={image.original_name} loading="lazy" decoding="async" draggable={false} />
                        </button>
                        {isBest && <span className="photo-series-badge">{t("bestChoice")}</span>}
                        <button
                          type="button"
                          className={`photo-tile-select${isKept ? " photo-tile-select-checked" : ""}`}
                          role="checkbox"
                          aria-checked={isKept}
                          aria-label={isKept ? t("unkeepAriaLabel", { name: image.original_name }) : t("keepAriaLabel", { name: image.original_name })}
                          onClick={() => toggleKeep(group.best_id, image.id)}
                        >
                          {isKept && (
                            <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M3 8.5l3 3 7-7" />
                            </svg>
                          )}
                        </button>
                      </div>
                      <span className="photo-series-caption muted">
                        {t("sharpnessCaption", { score: image.sharpness_score !== null ? image.sharpness_score.toFixed(1) : "–" })}
                        {isKept ? t("keptSuffix") : ""}
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
        />
      )}
    </div>
  );
}
