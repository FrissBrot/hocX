"use client";

import { useEffect, useRef, useState } from "react";

import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatTime } from "@/lib/utils/format";
import { FileBulkDeleteResult, FileOverviewItem, SimilarityGroup } from "@/types/api";
import { PhotoViewer } from "./photo-viewer";

export function PhotoSimilarGroups({
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
  // Which images stay when a group's selection is deleted - one Set per group (keyed by
  // best_id), seeded with just the best image once, then left to the user to extend. Deleting
  // never touches this set beyond removing gone ids - it's not re-seeded on every render, so a
  // group a user has already curated keeps its choices even as its `images` shrink.
  const [keepIds, setKeepIds] = useState<Record<string, Set<string>>>({});
  const [busyGroup, setBusyGroup] = useState<string | null>(null);
  const [viewer, setViewer] = useState<{ groupId: string; index: number } | null>(null);
  const requestIdRef = useRef(0);

  const tagKey = tagFilter.join(",");

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    const params = new URLSearchParams();
    params.set("min_size", "2");
    params.set("kind", "series");
    if (search.trim()) params.set("search", search.trim());
    tagFilter.forEach((tag) => params.append("tags", tag));
    browserApiFetch<SimilarityGroup[]>(`/api/files/similarity-groups?${params.toString()}`)
      .then((data) => {
        if (requestIdRef.current !== requestId) return;
        const list = data ?? [];
        setGroups(list);
        setKeepIds(Object.fromEntries(list.map((group) => [group.best_id, new Set([group.best_id])])));
      })
      .catch(() => {
        if (requestIdRef.current !== requestId) return;
        setError("Ähnliche Fotos konnten nicht geladen werden.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, tagKey]);

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
      showToast("Best-of-Status konnte nicht geändert werden.", "error");
    }
  }

  async function deleteSelection(group: SimilarityGroup) {
    const kept = keepIds[group.best_id] ?? new Set([group.best_id]);
    const candidates = group.images.filter((image) => !kept.has(image.id));
    const deletable = candidates.filter((image) => image.source === "gallery_upload");
    if (deletable.length === 0 || busyGroup) return;
    const ok = await confirm({
      tone: "danger",
      message: `${deletable.length} ${deletable.length === 1 ? "Bild wird" : "Bilder werden"} endgültig gelöscht. Die angehakten Fotos bleiben erhalten.`,
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
        showToast("Auswahl gelöscht - die Serie bleibt hier sichtbar.", "success");
      }
    } catch {
      showToast("Auswahl konnte nicht gelöscht werden.", "error");
    } finally {
      setBusyGroup(null);
    }
  }

  if (error) return <p className="form-error-banner">{error}</p>;
  if (!groups) return <p className="muted">Serien werden gruppiert…</p>;

  const visible = groups.filter((group) => !dismissed.has(group.best_id));
  const viewerGroup = visible.find((group) => group.best_id === viewer?.groupId);

  return (
    <div className="grid">
      <p className="muted">
        Ähnliche, aber nicht identische Aufnahmen (z. B. Serienbilder) werden hier als Serie gruppiert. Angehakte Fotos
        bleiben erhalten, der Rest kann in einem Schritt gelöscht werden - die Serie bleibt danach mit den verbleibenden
        Fotos weiter hier sichtbar.
      </p>
      {visible.length === 0 ? (
        <p className="muted">Keine ähnlichen Fotos gefunden.</p>
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
                  <span className="photo-series-title">Serie um {formatTime(best.created_at)} · {description}</span>
                  <span className="photo-series-count muted"> {group.images.length} ähnliche Fotos</span>
                </div>
                <div className="photo-series-actions">
                  <button type="button" className="button-ghost button-secondary" onClick={() => dismissGroup(group)} disabled={busyGroup === group.best_id}>
                    Serie ausblenden
                  </button>
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void deleteSelection(group)}
                    disabled={busyGroup === group.best_id || deletableCount === 0}
                    title={deletableCount === 0 ? "Nur direkt hochgeladene, nicht angehakte Fotos können hier gelöscht werden." : undefined}
                  >
                    Auswahl löschen
                  </button>
                </div>
              </div>
              {deletableCount < nonKept.length && deletableCount > 0 && (
                <p className="muted photo-series-hint">Einige nicht angehakte Fotos stammen aus Protokollen/Abgaben und werden beim Löschen übersprungen.</p>
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
                          aria-label={`${image.original_name} öffnen`}
                          onClick={() => setViewer({ groupId: group.best_id, index })}
                        >
                          <img src={thumbnailUrl} alt={image.original_name} loading="lazy" decoding="async" draggable={false} />
                        </button>
                        {isBest && <span className="photo-series-badge">Beste Wahl</span>}
                        <button
                          type="button"
                          className={`photo-tile-select${isKept ? " photo-tile-select-checked" : ""}`}
                          role="checkbox"
                          aria-checked={isKept}
                          aria-label={isKept ? `${image.original_name} nicht mehr behalten` : `${image.original_name} behalten`}
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
                        Schärfe {image.sharpness_score !== null ? image.sharpness_score.toFixed(1) : "–"}
                        {isKept ? " · behalten" : ""}
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
