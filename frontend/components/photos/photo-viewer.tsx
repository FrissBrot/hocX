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
  const hasFace = item.face_quality_score !== null;
  const faceMeter = (
    <PhotoMeter
      label="Gesichtsqualität"
      tone="face"
      value={
        item.face_analyzed_at === null
          ? null
          : item.face_quality_score !== null
            ? describeSharpness(item.face_quality_score)
            : "Kein Gesicht erkannt"
      }
      fraction={item.face_quality_score !== null ? sharpnessFraction(item.face_quality_score) : null}
      title={
        item.face_quality_score !== null
          ? `Rohwert (Schärfe des Gesichtsausschnitts, gewichtet nach Belichtung): ${item.face_quality_score.toFixed(1)}`
          : undefined
      }
    />
  );
  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;
  const thumbnailUrl = item.thumbnail_url ? `${browserApiBaseUrl}${item.thumbnail_url}` : fileUrl;
  const [readyUrl, setReadyUrl] = useState<string | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const loadingOriginal = readyUrl !== fileUrl && failedUrl !== fileUrl;
  const [metadata, setMetadata] = useState<StoredFileMetadata | null>(null);
  const [tagsValue, setTagsValue] = useState(item.tags.join(","));
  const [saving, setSaving] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasPrev = index > 0;
  const hasNext = index < items.length - 1;

  useEffect(() => {
    if (thumbnailUrl === fileUrl) return;
    let cancelled = false;
    const original = new Image();
    original.onload = async () => {
      try {
        await original.decode();
        if (!cancelled) setReadyUrl(fileUrl);
      } catch {
        // Keep the thumbnail if the original cannot be decoded.
        if (!cancelled) setFailedUrl(fileUrl);
      }
    };
    original.onerror = () => {
      if (!cancelled) setFailedUrl(fileUrl);
    };
    original.src = fileUrl;
    return () => {
      cancelled = true;
      original.onload = null;
      original.onerror = null;
    };
  }, [fileUrl, thumbnailUrl]);

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

  const dimensions = metadata?.width && metadata?.height ? `${metadata.width} × ${metadata.height} px` : null;
  const bezugParts = [item.albums[0]?.name, item.context_label].filter(Boolean);

  // Same SSR guard ui/lightbox-image.tsx already has for its own createPortal call -
  // this component was missing it (audit fix, 2026-09-17). In practice PhotoViewer is
  // only ever mounted once client-side state opens it, so this is a defensive safety net
  // rather than a bug hit today, not a reason to skip it.
  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div className="photo-viewer" role="dialog" aria-modal="true" aria-label={item.original_name}>
      <div className="photo-viewer-header">
        <div className="photo-viewer-header-left">
          <button type="button" className="photo-viewer-close" aria-label="Schliessen" onClick={onClose}>
            ✕
          </button>
          <div>
            <div className="photo-viewer-title">{item.original_name}</div>
            <div className="photo-viewer-subtitle">
              {item.group_date ? `${formatWeekdayDate(item.group_date)} · ` : ""}
              {index + 1}/{items.length}
            </div>
          </div>
        </div>
        <div className="photo-viewer-actions">
          <button type="button" className="pill" onClick={onClose}>Galerie</button>
          <button type="button" className="pill photo-viewer-pill-accent" onClick={() => onToggleBest(item)}>
            {item.is_best ? "★ Best-of" : "☆ Best-of"}
          </button>
          <a href={fileUrl} target="_blank" rel="noreferrer" className="pill photo-viewer-pill-solid">
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
          <img
            src={readyUrl === fileUrl ? fileUrl : thumbnailUrl}
            alt={item.original_name}
            className="photo-viewer-img"
            onLoad={() => { if (thumbnailUrl === fileUrl) setReadyUrl(fileUrl); }}
            onError={() => { if (thumbnailUrl === fileUrl) setFailedUrl(fileUrl); }}
          />
          {loadingOriginal && (
            <div className="photo-viewer-loading" role="status" aria-label="Originalbild wird geladen">
              <span className="photo-viewer-loading-spinner" aria-hidden="true" />
            </div>
          )}
          {hasNext && (
            <button type="button" className="photo-viewer-nav photo-viewer-nav-next" aria-label="Nächstes Foto" onClick={() => onIndexChange(index + 1)}>
              ›
            </button>
          )}
        </div>

        <div className="photo-viewer-sidebar">
          <div className="photo-viewer-section">
            <div className="photo-viewer-section-title">Analyse</div>
            {hasFace && faceMeter}
            <PhotoMeter
              label={hasFace ? "Schärfe (gesamtes Bild)" : "Schärfe"}
              tone="sharpness"
              value={item.sharpness_score !== null ? describeSharpness(item.sharpness_score) : null}
              fraction={item.sharpness_score !== null ? sharpnessFraction(item.sharpness_score) : null}
              title={item.sharpness_score !== null ? `Rohwert (Laplace-Varianz der schärfsten Bildbereiche): ${item.sharpness_score.toFixed(1)}` : undefined}
            />
            <PhotoMeter
              label="Belichtung"
              tone="exposure"
              value={item.exposure_score !== null ? describeExposure(item.exposure_score) : null}
              fraction={item.exposure_score}
              title={
                item.exposure_score !== null
                  ? `${Math.round((1 - item.exposure_score) * 100)}% der Pixel sind ausgebrannt oder abgesoffen`
                  : undefined
              }
            />
            {!hasFace && faceMeter}
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
              {item.file_size_bytes !== null && item.file_size_bytes !== undefined ? (
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
            <TagInput value={tagsValue} onChange={handleTagsChange} placeholder="+ Tag" alwaysShowPlaceholder />
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function PhotoMeter({
  label,
  value,
  fraction,
  tone,
  title,
}: {
  label: string;
  value: string | null;
  fraction: number | null;
  tone: "sharpness" | "exposure" | "face";
  title?: string;
}) {
  return (
    <div className="photo-meter-row" title={title}>
      <div className="photo-meter-label-row">
        <span className="photo-meter-label">{label}</span>
        <span className="photo-meter-value">{value ?? "Analyse ausstehend"}</span>
      </div>
      <div className="photo-meter-bar">
        <div
          className={`photo-meter-fill photo-meter-fill-${tone}`}
          style={{ width: `${fraction !== null ? Math.round(fraction * 100) : 0}%` }}
        />
      </div>
    </div>
  );
}

// Schärfe und Gesichtsqualität sind rohe Laplace-Varianzen ohne Obergrenze (typisch ~10 bis
// mehrere Tausend, stark motiv- und rauschabhängig). Für die Anzeige werden sie logarithmisch
// auf 0-100 abgebildet und in Stufen beschriftet; der Rohwert steht im Tooltip.
const SHARPNESS_LOG_CEILING = Math.log10(1 + 10000);

function sharpnessFraction(score: number): number {
  return Math.min(1, Math.max(0, Math.log10(1 + Math.max(0, score)) / SHARPNESS_LOG_CEILING));
}

function describeSharpness(score: number): string {
  const label = score < 50 ? "Unscharf" : score < 300 ? "Mittel" : score < 1500 ? "Scharf" : "Sehr scharf";
  return `${label} · ${Math.round(sharpnessFraction(score) * 100)}/100`;
}

function describeExposure(score: number): string {
  const label = score >= 0.95 ? "Gut" : score >= 0.85 ? "Leichtes Clipping" : "Starkes Clipping";
  return `${label} · ${Math.round(score * 100)}%`;
}
