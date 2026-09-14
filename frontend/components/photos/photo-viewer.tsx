"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { TagInput } from "@/components/ui/tag-input";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize, formatWeekdayDate } from "@/lib/utils/format";
import { FileOverviewItem, StoredFileMetadata } from "@/types/api";

export function PhotoViewer({
  items,
  index,
  onIndexChange,
  onClose,
  onToggleBest,
  onTagsSaved,
}: {
  items: FileOverviewItem[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  onToggleBest: (item: FileOverviewItem) => void;
  onTagsSaved: (id: string, tags: string[]) => void;
}) {
  const item = items[index];
  const [metadata, setMetadata] = useState<StoredFileMetadata | null>(null);
  const [tagsValue, setTagsValue] = useState(item.tags.join(","));
  const [saving, setSaving] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasPrev = index > 0;
  const hasNext = index < items.length - 1;

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft" && hasPrev) onIndexChange(index - 1);
      if (event.key === "ArrowRight" && hasNext) onIndexChange(index + 1);
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [hasPrev, hasNext, index, onClose, onIndexChange]);

  useEffect(() => {
    setTagsValue(item.tags.join(","));
    setMetadata(null);
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => setMetadata(data))
      .catch(() => setMetadata(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  function handleTagsChange(value: string) {
    setTagsValue(value);
    const tags = value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [];
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      setSaving(true);
      try {
        const saved = await browserApiFetch<string[]>(item.tags_url, { method: "PATCH", body: JSON.stringify({ tags }) });
        onTagsSaved(item.id, saved ?? tags);
      } finally {
        setSaving(false);
      }
    }, 500);
  }

  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;
  const dimensions = metadata?.width && metadata?.height ? `${metadata.width} × ${metadata.height} px` : null;
  const bezugParts = [item.albums[0]?.name, item.context_label].filter(Boolean);

  return createPortal(
    <div className="photo-viewer" role="dialog" aria-modal="true" aria-label={item.original_name}>
      <div className="photo-viewer-header">
        <div>
          <div className="photo-viewer-title">{item.original_name}</div>
          <div className="photo-viewer-subtitle">
            {item.group_date ? `${formatWeekdayDate(item.group_date)} · ` : ""}
            {index + 1}/{items.length}
          </div>
        </div>
        <div className="photo-viewer-actions">
          <button type="button" className="pill" onClick={() => onToggleBest(item)}>
            {item.is_best ? "★ Best-of" : "☆ Best-of"}
          </button>
          <button type="button" className="pill" onClick={onClose}>Galerie</button>
          <a href={fileUrl} target="_blank" rel="noreferrer" className="button-inline button-ghost">
            Original öffnen
          </a>
        </div>
      </div>

      <div className="photo-viewer-body">
        <div className="photo-viewer-stage">
          {hasPrev && (
            <button type="button" className="photo-viewer-nav photo-viewer-nav-prev" aria-label="Vorheriges Foto" onClick={() => onIndexChange(index - 1)}>
              ‹
            </button>
          )}
          <img src={fileUrl} alt={item.original_name} className="photo-viewer-img" />
          {hasNext && (
            <button type="button" className="photo-viewer-nav photo-viewer-nav-next" aria-label="Nächstes Foto" onClick={() => onIndexChange(index + 1)}>
              ›
            </button>
          )}
        </div>

        <div className="photo-viewer-sidebar">
          <div className="photo-viewer-section">
            <div className="photo-viewer-section-title">Analyse</div>
            <PhotoMeter
              label="Schärfe"
              value={item.sharpness_score !== null ? item.sharpness_score.toFixed(1) : null}
              fraction={item.sharpness_score !== null ? Math.min(1, item.sharpness_score / 100) : null}
            />
            <PhotoMeter
              label="Belichtung"
              value={item.exposure_score !== null ? `${Math.round(item.exposure_score * 100)}%` : null}
              fraction={item.exposure_score}
            />
            <PhotoMeter
              label="Gesichtsqualität"
              value={
                item.face_analyzed_at === null
                  ? null
                  : item.face_quality_score !== null
                    ? `${item.face_quality_score.toFixed(1)} / 10`
                    : "Kein Gesicht erkannt"
              }
              fraction={item.face_quality_score !== null ? Math.min(1, item.face_quality_score / 10) : null}
            />
          </div>

          <div className="photo-viewer-section">
            <div className="photo-viewer-section-title">Details</div>
            <dl className="photo-viewer-details">
              {bezugParts.length > 0 && (
                <div>
                  <dt>Bezug</dt>
                  <dd>{bezugParts.join(" · ")}</dd>
                </div>
              )}
              <div>
                <dt>Aufgenommen</dt>
                <dd>{formatDateTime(metadata?.exif_taken_at ?? item.created_at)}</dd>
              </div>
              {dimensions && (
                <div>
                  <dt>Bildmasse</dt>
                  <dd>{dimensions}</dd>
                </div>
              )}
              {item.file_size_bytes ? (
                <div>
                  <dt>Grösse</dt>
                  <dd>{formatFileSize(item.file_size_bytes)}</dd>
                </div>
              ) : null}
              {metadata?.exif_camera && (
                <div>
                  <dt>Kamera</dt>
                  <dd>{metadata.exif_camera}</dd>
                </div>
              )}
              <div>
                <dt>Herkunft</dt>
                <dd>{item.origin_tag}</dd>
              </div>
            </dl>
          </div>

          <div className="photo-viewer-section">
            <div className="photo-viewer-section-title">
              Tags {saving ? <span className="muted">(speichert…)</span> : null}
            </div>
            <TagInput value={tagsValue} onChange={handleTagsChange} placeholder="Tag hinzufügen…" />
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function PhotoMeter({ label, value, fraction }: { label: string; value: string | null; fraction: number | null }) {
  return (
    <div className="photo-meter-row">
      <div className="photo-meter-label-row">
        <span className="photo-meter-label">{label}</span>
        <span className="photo-meter-value">{value ?? "Analyse ausstehend"}</span>
      </div>
      <div className="photo-meter-bar">
        <div className="photo-meter-fill" style={{ width: `${fraction !== null ? Math.round(fraction * 100) : 0}%` }} />
      </div>
    </div>
  );
}
