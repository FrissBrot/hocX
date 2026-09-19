"use client";

import { useEffect, useRef, useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatTime } from "@/lib/utils/format";
import { FileBulkDeleteResult, SimilarityGroup } from "@/types/api";

export function PhotoSimilarSeries({
  search,
  tagFilter,
  onDeleted,
}: {
  search: string;
  tagFilter: string[];
  onDeleted?: (deletedIds: string[]) => void;
}) {
  const confirm = useConfirm();
  const showToast = useToast();
  const [groups, setGroups] = useState<SimilarityGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [busyGroup, setBusyGroup] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const tagKey = tagFilter.join(",");

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const params = new URLSearchParams();
    params.set("min_size", "2");
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    browserApiFetch<SimilarityGroup[]>(`/api/files/similarity-groups?${params.toString()}`)
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        setGroups(data ?? []);
      })
      .catch(() => {
        if (requestIdRef.current !== requestId) return;
        setError("Ähnliche Fotos konnten nicht geladen werden.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagKey]);

  function keepSeries(group: SimilarityGroup) {
    setDismissed((current) => new Set(current).add(group.best_id));
  }

  async function keepOnlyBest(group: SimilarityGroup) {
    const rest = group.images.filter((image) => image.id !== group.best_id);
    if (rest.length === 0 || busyGroup) return;
    const ok = await confirm({
      tone: "danger",
      message: `${rest.length} ${rest.length === 1 ? "Bild wird" : "Bilder werden"} endgültig gelöscht. Nur das schärfste, am besten belichtete Foto der Serie bleibt erhalten.`,
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
        showToast("Serie bereinigt - nur das beste Foto bleibt.", "success");
      }
    } catch {
      showToast("Serie konnte nicht bereinigt werden.", "error");
    } finally {
      setBusyGroup(null);
    }
  }

  if (error) return <p className="form-error-banner">{error}</p>;
  if (!groups) return <p className="muted">Serien werden gruppiert…</p>;

  const visible = groups.filter((group) => !dismissed.has(group.best_id));

  return (
    <div className="grid">
      <p className="muted">
        Nahezu identische Aufnahmen werden zu Serien gruppiert. Das schärfste, am besten belichtete Foto jeder Serie ist
        vorausgewählt – die übrigen können in einem Schritt verworfen werden.
      </p>
      {visible.length === 0 ? (
        <p className="muted">Keine ähnlichen Fotos gefunden.</p>
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
                  <span className="photo-series-title">Serie um {formatTime(best.created_at)} · {description}</span>
                  <span className="photo-series-count muted"> {group.images.length} ähnliche Fotos</span>
                </div>
                <div className="photo-series-actions">
                  <button type="button" className="button-ghost button-inline" onClick={() => keepSeries(group)} disabled={busyGroup === group.best_id}>
                    Serie behalten
                  </button>
                  <button
                    type="button"
                    className="button-inline"
                    onClick={() => void keepOnlyBest(group)}
                    disabled={busyGroup === group.best_id || deletableCount === 0}
                    title={deletableCount === 0 ? "Nur direkt hochgeladene Fotos können hier gelöscht werden." : undefined}
                  >
                    Nur beste behalten
                  </button>
                </div>
              </div>
              {deletableCount < otherCount && deletableCount > 0 && (
                <p className="muted photo-series-hint">Einige Fotos dieser Serie stammen aus Protokollen/Abgaben und werden beim Bereinigen übersprungen.</p>
              )}
              <div className="photo-series-strip">
                {group.images.map((image) => {
                  const isBest = image.id === group.best_id;
                  const thumbnailUrl = image.thumbnail_url ? `${browserApiBaseUrl}${image.thumbnail_url}` : `${browserApiBaseUrl}${image.content_url}`;
                  return (
                    <div key={image.id} className={`photo-series-item${isBest ? " photo-series-item-best" : ""}`}>
                      <div className="photo-series-thumb-wrap">
                        <img src={thumbnailUrl} alt={image.original_name} loading="lazy" decoding="async" />
                        {isBest && <span className="photo-series-badge">Beste Wahl</span>}
                      </div>
                      <span className="photo-series-caption muted">
                        Schärfe {image.sharpness_score !== null ? image.sharpness_score.toFixed(1) : "–"}
                        {isBest ? " · beste Wahl" : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
