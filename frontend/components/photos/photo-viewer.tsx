"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";
import { LivePhotoClip } from "@/components/photos/live-photo-clip";
import { TagInput } from "@/components/ui/tag-input";
import { useDeferredPopupSave } from "@/lib/hooks/use-deferred-popup-save";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize, formatWeekdayDate } from "@/lib/utils/format";
import { FileOverviewItem, StoredFileMetadata } from "@/types/api";

// Was ein Live Photo beim Herunterladen liefert - siehe GET /stored-files/{id}/download?part=.
const LIVE_DOWNLOAD_OPTIONS = [
  { part: "image", label: "Bild (JPEG)" },
  { part: "video", label: "Video (MP4)" },
  { part: "both", label: "Bild und Video (ZIP)" },
];

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
  const { schedule, flush, saving, saveError } = useDeferredPopupSave();
  // Live Photo: spielt, solange der Zeiger über der Bühne liegt, oder per LIVE-Knopf (Touch/Tastatur).
  const [liveHover, setLiveHover] = useState(false);
  const [livePinned, setLivePinned] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);


  const rootRef = useRef<HTMLDivElement>(null);
  const downloadRef = useRef<HTMLDivElement>(null);
  usePopupEscape(true, saveAndClose, rootRef);
  usePopupEscape(downloadOpen, () => setDownloadOpen(false), downloadRef);
  usePopupScrollLock(true);

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
      if (event.key === "ArrowLeft" && hasPrev) onIndexChange(index - 1);
      if (event.key === "ArrowRight" && hasNext) onIndexChange(index + 1);
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [hasPrev, hasNext, index, onClose, onIndexChange]);

  useEffect(() => {
    setLiveHover(false);
    setLivePinned(false);
    setDownloadOpen(false);
  }, [item.id]);

  useEffect(() => {
    setTagsValue(item.tags.join(","));
    setMetadata(null);
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => setMetadata(data))
      .catch(() => setMetadata(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  function handleTagsChange(value: string) {
    setTagsValue(value);
    const tags = value ? value.split(",").map((t) => t.trim()).filter(Boolean) : [];
    schedule(async () => {
      const saved = await browserApiFetch<string[]>(item.tags_url, { method: "PATCH", body: JSON.stringify({ tags }) });
      onTagsSaved(item.id, saved ?? tags);
    });
  }

  async function saveAndClose() {
    if (await flush()) onClose();
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
    <div ref={rootRef} className="photo-viewer" role="dialog" aria-modal="true" aria-label={item.original_name}>
      {saveError && <p role="alert">{saveError}</p>}
      <div className="photo-viewer-header">
        <div className="photo-viewer-header-left">
          <button type="button" className="photo-viewer-close" aria-label="Schliessen" onClick={() => void saveAndClose()}>
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
          <button type="button" className="pill" onClick={() => void saveAndClose()}>Galerie</button>
          <button type="button" className="pill photo-viewer-pill-accent" onClick={() => onToggleBest(item)}>
            {item.is_best ? "★ Best-of" : "☆ Best-of"}
          </button>
          {item.live_video_url && (
            <div ref={downloadRef} className="photo-viewer-download">
              <button
                type="button"
                className="pill"
                aria-haspopup="menu"
                aria-expanded={downloadOpen}
                onClick={() => setDownloadOpen((open) => !open)}
              >
                Herunterladen ▾
              </button>
              {downloadOpen && (
                <div className="dropdown-panel dropdown-panel-down" role="menu">
                  <div className="dropdown-panel-scroll">
                    {LIVE_DOWNLOAD_OPTIONS.map((option) => (
                      <a
                        key={option.part}
                        role="menuitem"
                        className="dropdown-option"
                        href={`${browserApiBaseUrl}/api/stored-files/${item.id}/download?part=${option.part}`}
                        onClick={() => setDownloadOpen(false)}
                      >
                        {option.label}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <a href={fileUrl} target="_blank" rel="noreferrer" className="pill photo-viewer-pill-solid">
            Original öffnen
          </a>
        </div>
      </div>

      <div className="photo-viewer-body">
        <div
          className="photo-viewer-stage"
          onMouseEnter={item.live_video_url ? () => setLiveHover(true) : undefined}
          onMouseLeave={item.live_video_url ? () => setLiveHover(false) : undefined}
        >
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
          {item.live_video_url && (
            <>
              <LivePhotoClip
                key={item.id}
                src={`${browserApiBaseUrl}${item.live_video_url}`}
                active={liveHover || livePinned}
                className="photo-viewer-live-video"
              />
              <button
                type="button"
                className="photo-viewer-live"
                aria-pressed={livePinned}
                aria-label="Live Photo abspielen"
                onClick={() => setLivePinned((pinned) => !pinned)}
              >
                LIVE
              </button>
            </>
          )}
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
