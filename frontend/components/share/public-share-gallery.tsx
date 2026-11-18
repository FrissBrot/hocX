"use client";

// Öffentliche Teilen-Seite /share/<token> (Design «hocX Public Teilen»): Kopf mit Absender und
// Download-Aktionen, Titelbereich, Dateien als Kacheln oder Liste bzw. Fotoalbum als Masonry,
// Vollbild-Ansicht mit Filmstreifen. Alle Daten kommen aus GET /api/public/share/<token>.
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";

import { FileTypeIcon } from "@/components/files/file-type-icon";
import { ActionIcon } from "@/components/ui/action-icons";
import { fileExtension } from "@/lib/files/display";
import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";
import { formatFileSize, formatLongDateRange, formatShortMonthDate } from "@/lib/utils/format";
import { PublicShare, PublicShareFile } from "@/types/api";

const HOCX_LANDING_URL = "https://hocx.ch";

type ShareView = "grid" | "list";

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v12" />
      <path d="m6 11 6 6 6-6" />
      <path d="M5 20h14" />
    </svg>
  );
}

function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={direction === "left" ? "m15 6-6 6 6 6" : "m9 6 6 6-6 6"} />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 5 5 9-10" />
    </svg>
  );
}

function initialsOf(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

/** Kennzeichen-Farbe je Dateiart, wie die Kacheln im Dateien-Tab. */
function extensionTone(extension: string): string {
  if (extension === "pdf") return "pdf";
  if (["doc", "docx", "odt", "rtf", "txt", "md"].includes(extension)) return "doc";
  if (["xls", "xlsx", "ods", "csv"].includes(extension)) return "sheet";
  if (["zip", "rar", "7z", "tar", "gz"].includes(extension)) return "zip";
  if (["jpg", "jpeg", "png", "gif", "webp", "heic", "svg"].includes(extension)) return "image";
  if (["mp3", "wav", "m4a", "ogg", "flac"].includes(extension)) return "audio";
  return "file";
}

function ExtensionBadge({ file }: { file: PublicShareFile }) {
  const extension = fileExtension(file.original_name);
  if (!extension) return null;
  return <span className={`public-share-ext public-share-ext-${extensionTone(extension)}`}>{extension.slice(0, 5).toUpperCase()}</span>;
}

function FileMeta({ file }: { file: PublicShareFile }) {
  const t = useTranslations("share.publicPage");
  const parts: string[] = [];
  if (file.page_count) parts.push(t("pageCount", { count: file.page_count }));
  if (file.file_size_bytes) parts.push(formatFileSize(file.file_size_bytes));
  return <>{parts.join(" · ")}</>;
}

/** Vorschau einer Datei: Foto bzw. erste Dokumentseite vom Server, sonst eine schlichte Typ-Kachel. */
function FilePreview({ file, variant }: { file: PublicShareFile; variant: "tile" | "row" }) {
  const [failed, setFailed] = useState(false);
  if (file.thumbnail_url && !failed) {
    return (
      <span className={file.is_image ? `public-share-preview-photo public-share-preview-photo-${variant}` : `public-share-preview-page public-share-preview-page-${variant}`}>
        {/* eslint-disable-next-line @next/next/no-img-element -- Vorschau kommt vom öffentlichen Link-Endpunkt */}
        <img src={file.thumbnail_url} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
      </span>
    );
  }
  return (
    <span className={`public-share-preview-type public-share-preview-type-${variant}`}>
      <FileTypeIcon name={file.original_name} />
    </span>
  );
}

function SelectCheck({ selected }: { selected: boolean }) {
  return (
    <span className={selected ? "public-share-check public-share-check-on" : "public-share-check"} aria-hidden="true">
      {selected ? <CheckIcon /> : null}
    </span>
  );
}

export function PublicShareGallery({ share }: { share: PublicShare }) {
  const t = useTranslations("share.publicPage");
  const locale = useLocale();
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [view, setView] = useState<ShareView>("grid");

  const files = share.files;
  const isPhotoAlbum = files.length > 0 && files.every((file) => file.is_image && file.thumbnail_url);
  const dateRange = formatLongDateRange(share.date_from, share.date_to, locale);
  const allSelected = files.length > 0 && selected.size === files.length;

  const selectedUrl = useMemo(() => {
    if (!share.download_all_url || selected.size === 0) return null;
    if (selected.size === files.length) return share.download_all_url;
    // Reihenfolge des Links beibehalten, nicht die Klick-Reihenfolge.
    const ids = files.filter((file) => selected.has(file.id)).map((file) => file.id);
    return `${share.download_all_url}?ids=${ids.join(",")}`;
  }, [selected, share.download_all_url, files]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(files.map((file) => file.id)));
  }

  function stopSelecting() {
    setSelecting(false);
    setSelected(new Set());
  }

  function activate(index: number) {
    if (selecting) toggle(files[index].id);
    else setViewerIndex(index);
  }

  function tileLabel(file: PublicShareFile) {
    return selecting ? t("toggleSelect", { name: file.original_name }) : t("open", { name: file.original_name });
  }

  return (
    <div className="public-share-page">
      <header className="public-share-topbar">
        <div className="public-share-topbar-inner">
          <div className="public-share-sender">
            <span className="public-share-avatar" aria-hidden="true">{initialsOf(share.tenant_name)}</span>
            <div className="public-share-sender-text">
              <strong>{share.tenant_name}</strong>
              <span className="muted">{share.is_album ? t("sharedAlbum") : t("sharedFiles")}</span>
            </div>
          </div>
          {share.download_all_url ? (
            <div className={selecting ? "public-share-actions public-share-actions-selecting" : "public-share-actions"}>
              {selecting ? (
                <>
                  <span className="public-share-selected-count" role="status">{t("selectedCount", { count: selected.size })}</span>
                  <button type="button" className="button-secondary" onClick={toggleAll}>
                    {allSelected ? t("selectNone") : t("selectAll")}
                  </button>
                  <button type="button" className="button-ghost" onClick={stopSelecting}>
                    {t("cancelSelect")}
                  </button>
                  {selectedUrl ? (
                    <a href={selectedUrl} className="button-primary public-share-download" download>
                      <DownloadIcon />
                      {t("downloadSelection")}
                    </a>
                  ) : (
                    <button type="button" className="button-primary public-share-download" disabled>
                      <DownloadIcon />
                      {t("downloadSelection")}
                    </button>
                  )}
                </>
              ) : (
                <>
                  <button type="button" className="button-secondary" onClick={() => setSelecting(true)}>
                    {t("select")}
                  </button>
                  <a href={share.download_all_url} className="button-primary public-share-download" download>
                    <DownloadIcon />
                    {t("downloadAll")}
                  </a>
                </>
              )}
            </div>
          ) : null}
        </div>
      </header>

      <main className="public-share-main">
        <div className="public-share-hero">
          <div className="public-share-hero-text">
            <p className="public-share-eyebrow">{share.context ?? (share.is_album || isPhotoAlbum ? t("eyebrowAlbum") : t("eyebrowFiles"))}</p>
            <h1 className="public-share-title">{share.name}</h1>
            <p className="public-share-meta muted">
              <span>{isPhotoAlbum ? t("photoCount", { count: files.length }) : t("fileCount", { count: files.length })}</span>
              {share.total_size_bytes > 0 ? <span>{formatFileSize(share.total_size_bytes)}</span> : null}
              {dateRange ? <span>{dateRange}</span> : null}
              {share.expires_at ? <span>{t("validUntil", { date: formatShortMonthDate(share.expires_at, locale) })}</span> : null}
            </p>
          </div>
          {!isPhotoAlbum && files.length > 0 ? (
            <div className="public-share-view-toggle" role="group" aria-label={t("viewLabel")}>
              <button
                type="button"
                className={view === "grid" ? "button-icon public-share-view-toggle-active" : "button-icon"}
                aria-pressed={view === "grid"}
                aria-label={t("viewGrid")}
                title={t("viewGrid")}
                onClick={() => setView("grid")}
              >
                <ActionIcon name="grid" />
              </button>
              <button
                type="button"
                className={view === "list" ? "button-icon public-share-view-toggle-active" : "button-icon"}
                aria-pressed={view === "list"}
                aria-label={t("viewList")}
                title={t("viewList")}
                onClick={() => setView("list")}
              >
                <ActionIcon name="list" />
              </button>
            </div>
          ) : null}
        </div>

        {files.length === 0 ? (
          <p className="muted">{t("noFiles")}</p>
        ) : isPhotoAlbum ? (
          <ul className={selecting ? "public-share-masonry public-share-masonry-selecting" : "public-share-masonry"}>
            {files.map((file, index) => {
              const isSelected = selected.has(file.id);
              const ratio = file.width && file.height ? `${file.width} / ${file.height}` : undefined;
              return (
                <li key={file.id} className="public-share-tile-wrap">
                  <button
                    type="button"
                    className={isSelected ? "public-share-tile public-share-tile-selected" : "public-share-tile"}
                    onClick={() => activate(index)}
                    aria-pressed={selecting ? isSelected : undefined}
                    aria-label={tileLabel(file)}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- Vorschau kommt vom öffentlichen Link-Endpunkt */}
                    <img
                      src={file.thumbnail_url ?? ""}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      className="public-share-tile-img"
                      style={ratio ? { aspectRatio: ratio } : undefined}
                    />
                    {selecting ? <SelectCheck selected={isSelected} /> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : view === "grid" ? (
          <ul className={selecting ? "public-share-grid public-share-grid-selecting" : "public-share-grid"}>
            {files.map((file, index) => {
              const isSelected = selected.has(file.id);
              return (
                <li key={file.id} className={isSelected ? "public-share-file public-share-file-selected" : "public-share-file"}>
                  <button
                    type="button"
                    className="public-share-file-open"
                    onClick={() => activate(index)}
                    aria-pressed={selecting ? isSelected : undefined}
                    aria-label={tileLabel(file)}
                  >
                    <span className="public-share-file-preview">
                      <FilePreview file={file} variant="tile" />
                      <ExtensionBadge file={file} />
                      {selecting ? <SelectCheck selected={isSelected} /> : null}
                    </span>
                    <span className="public-share-file-name" title={file.original_name}>{file.original_name}</span>
                  </button>
                  <span className="public-share-file-meta">
                    <span className="public-share-file-meta-text">
                      <FileMeta file={file} />
                    </span>
                    <a
                      href={file.download_url}
                      className="button-icon-soft button-icon-soft-sm public-share-file-download"
                      download
                      aria-label={t("downloadFile", { name: file.original_name })}
                      title={t("download")}
                    >
                      <ActionIcon name="download" />
                    </a>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <ul className="public-share-list">
            {files.map((file, index) => {
              const isSelected = selected.has(file.id);
              return (
                <li key={file.id} className={isSelected ? "public-share-row public-share-row-selected" : "public-share-row"}>
                  <button
                    type="button"
                    className="public-share-row-open"
                    onClick={() => activate(index)}
                    aria-pressed={selecting ? isSelected : undefined}
                    aria-label={tileLabel(file)}
                  >
                    {selecting ? <SelectCheck selected={isSelected} /> : null}
                    <FilePreview file={file} variant="row" />
                    <span className="public-share-row-text">
                      <span className="public-share-row-name" title={file.original_name}>{file.original_name}</span>
                      <span className="public-share-row-meta">
                        <ExtensionBadge file={file} />
                        <FileMeta file={file} />
                      </span>
                    </span>
                  </button>
                  <a
                    href={file.download_url}
                    className="button-icon-soft public-share-row-download"
                    download
                    aria-label={t("downloadFile", { name: file.original_name })}
                    title={t("download")}
                  >
                    <ActionIcon name="download" />
                  </a>
                </li>
              );
            })}
          </ul>
        )}
      </main>

      <footer className="public-share-footer">
        <div className="public-share-footer-inner">
          <p>{isPhotoAlbum ? t("footerNotice") : t("footerNoticeFiles")}</p>
          <p>
            {t.rich("sharedWith", {
              brand: (chunks) => (
                <a href={HOCX_LANDING_URL} target="_blank" rel="noopener noreferrer" className="public-share-brand">
                  {chunks}
                </a>
              )
            })}
          </p>
        </div>
      </footer>

      {viewerIndex !== null && files[viewerIndex] ? (
        <PublicShareViewer files={files} index={viewerIndex} onIndexChange={setViewerIndex} onClose={() => setViewerIndex(null)} />
      ) : null}
    </div>
  );
}

function ViewerStage({ file }: { file: PublicShareFile }) {
  const t = useTranslations("share.publicPage");
  const stop = (event: MouseEvent) => event.stopPropagation();
  if (file.is_image && file.view_url) {
    // eslint-disable-next-line @next/next/no-img-element -- Original kommt vom öffentlichen Link-Endpunkt
    return <img key={file.id} src={file.view_url} alt={file.original_name} className="public-share-viewer-img" onClick={stop} />;
  }
  if (file.thumbnail_url) {
    return (
      <span className="public-share-viewer-page" onClick={stop}>
        {/* eslint-disable-next-line @next/next/no-img-element -- Seitenvorschau kommt vom öffentlichen Link-Endpunkt */}
        <img key={file.id} src={file.thumbnail_url} alt={file.original_name} />
      </span>
    );
  }
  return (
    <div className="public-share-viewer-empty" onClick={stop}>
      <FileTypeIcon name={file.original_name} />
      <strong>{file.original_name}</strong>
      <span>{t("noPreview")}</span>
      <a href={file.download_url} className="public-share-viewer-download" download>
        <DownloadIcon />
        {t("download")}
      </a>
    </div>
  );
}

function PublicShareViewer({
  files,
  index,
  onIndexChange,
  onClose
}: {
  files: PublicShareFile[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}) {
  const t = useTranslations("share.publicPage");
  const rootRef = useRef<HTMLDivElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  usePopupEscape(true, onClose, rootRef);
  usePopupScrollLock(true);

  const file = files[index];
  const hasPrev = index > 0;
  const hasNext = index < files.length - 1;
  const go = useCallback(
    (delta: number) => {
      const next = Math.min(Math.max(index + delta, 0), files.length - 1);
      if (next !== index) onIndexChange(next);
    },
    [files.length, index, onIndexChange]
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowLeft") go(-1);
      if (event.key === "ArrowRight") go(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  useEffect(() => {
    const active = stripRef.current?.querySelector<HTMLElement>("[aria-current='true']");
    active?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [index]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div ref={rootRef} className="public-share-viewer" role="dialog" aria-modal="true" aria-label={file.original_name} onClick={onClose}>
      <div className="public-share-viewer-bar" onClick={(event) => event.stopPropagation()}>
        <div className="public-share-viewer-info">
          <ExtensionBadge file={file} />
          <span className="public-share-viewer-title">
            <strong title={file.original_name}>{file.original_name}</strong>
            <span>
              {t("position", { index: index + 1, total: files.length })}
              {file.page_count ? ` · ${t("pageCount", { count: file.page_count })}` : null}
              {file.file_size_bytes ? ` · ${formatFileSize(file.file_size_bytes)}` : null}
            </span>
          </span>
        </div>
        <div className="public-share-viewer-actions">
          <a href={file.download_url} className="public-share-viewer-download" download aria-label={t("download")}>
            <DownloadIcon />
            <span className="public-share-viewer-download-label">{t("download")}</span>
          </a>
          <button type="button" className="public-share-viewer-round" onClick={onClose} aria-label={t("close")}>
            <ActionIcon name="close" width={18} height={18} />
          </button>
        </div>
      </div>
      <div className="public-share-viewer-stage">
        <ViewerStage file={file} />
      </div>
      {hasPrev ? (
        <button
          type="button"
          className="public-share-viewer-round public-share-viewer-nav public-share-viewer-prev"
          onClick={(event) => {
            event.stopPropagation();
            go(-1);
          }}
          aria-label={t("previous")}
        >
          <ChevronIcon direction="left" />
        </button>
      ) : null}
      {hasNext ? (
        <button
          type="button"
          className="public-share-viewer-round public-share-viewer-nav public-share-viewer-next"
          onClick={(event) => {
            event.stopPropagation();
            go(1);
          }}
          aria-label={t("next")}
        >
          <ChevronIcon direction="right" />
        </button>
      ) : null}
      {files.length > 1 ? (
        <div ref={stripRef} className="public-share-viewer-strip" role="group" aria-label={t("filmstrip")} onClick={(event) => event.stopPropagation()}>
          {files.map((item, itemIndex) => (
            <button
              key={item.id}
              type="button"
              className={itemIndex === index ? "public-share-strip-item public-share-strip-item-active" : "public-share-strip-item"}
              aria-current={itemIndex === index ? "true" : undefined}
              aria-label={t("open", { name: item.original_name })}
              onClick={() => onIndexChange(itemIndex)}
            >
              {item.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- Vorschau kommt vom öffentlichen Link-Endpunkt
                <img src={item.thumbnail_url} alt="" loading="lazy" decoding="async" />
              ) : (
                <span className="public-share-strip-type">{(fileExtension(item.original_name) || "?").slice(0, 4).toUpperCase()}</span>
              )}
            </button>
          ))}
        </div>
      ) : null}
    </div>,
    document.body
  );
}
