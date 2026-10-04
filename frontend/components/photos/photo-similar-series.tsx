"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatTime } from "@/lib/utils/format";
import { FileBulkDeleteResult, FileOverviewItem, SimilarityGroup } from "@/types/api";
import { PhotoViewer } from "./photo-viewer";

export function PhotoSimilarSeries({
  search,
  tagFilter,
  onDeleted,
}: {
  search: string;
  tagFilter: string[];
  onDeleted?: (deletedIds: string[]) => void;
}) {
  const t = useTranslations("photos.similarSeries");
  const confirm = useConfirm();
  const showToast = useToast();
  const [groups, setGroups] = useState<SimilarityGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [busyGroup, setBusyGroup] = useState<string | null>(null);
  const [viewer, setViewer] = useState<{ groupId: string; index: number } | null>(null);
  const requestIdRef = useRef(0);

  const tagKey = tagFilter.join(",");

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const params = new URLSearchParams();
    params.set("min_size", "2");
    params.set("kind", "duplicate");
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    browserApiFetch<SimilarityGroup[]>(`/api/files/similarity-groups?${params.toString()}`)
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        setGroups(data ?? []);
      })
      .catch(() => {
        if (requestIdRef.current !== requestId) return;
        setError(t("loadError"));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagKey]);

  function keepSeries(group: SimilarityGroup) {
    setDismissed((current) => new Set(current).add(group.best_id));
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
      setDismissed((current) => new Set(current).add(group.best_id));
      const deletedCount = result?.deleted_ids.length ?? 0;
      if (result && deletedCount > 0) onDeleted?.(result.deleted_ids);
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

  if (error) return <p className="form-error-banner">{error}</p>;
  if (!groups) return <p className="muted">{t("loading")}</p>;

  const visible = groups.filter((group) => !dismissed.has(group.best_id));
  const viewerGroup = visible.find((group) => group.best_id === viewer?.groupId);

  return (
    <div className="grid">
      <p className="muted">
        {t("intro")}
      </p>
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
        />
      )}
    </div>
  );
}
