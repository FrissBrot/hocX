"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";
import { formatFileSize, formatLongDateRange, formatShortMonthDate } from "@/lib/utils/format";
import { PublicShare, PublicShareFile } from "@/types/api";

const HOCX_LANDING_URL = "https://hocx.ch";

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

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" width="32" height="32" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

function initialsOf(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

export function PublicShareGallery({ share }: { share: PublicShare }) {
  const t = useTranslations("share.publicPage");
  const locale = useLocale();
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);

  const images = useMemo(() => share.files.filter((file) => file.is_image && file.view_url), [share.files]);
  const allImages = images.length === share.files.length;
  const dateRange = formatLongDateRange(share.date_from, share.date_to, locale);

  const selectedUrl = useMemo(() => {
    if (!share.download_all_url || selected.size === 0) return null;
    if (selected.size === share.files.length) return share.download_all_url;
    // Reihenfolge des Links beibehalten, nicht die Klick-Reihenfolge.
    const ids = share.files.filter((file) => selected.has(file.id)).map((file) => file.id);
    return `${share.download_all_url}?ids=${ids.join(",")}`;
  }, [selected, share.download_all_url, share.files]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function stopSelecting() {
    setSelecting(false);
    setSelected(new Set());
  }

  function openFile(file: PublicShareFile) {
    const index = images.findIndex((image) => image.id === file.id);
    if (index >= 0) setViewerIndex(index);
    else window.location.href = file.download_url;
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
            <div className="public-share-actions">
              {selecting ? (
                <>
                  <button type="button" className="button-ghost" onClick={stopSelecting}>
                    {t("cancelSelect")}
                  </button>
                  {selectedUrl ? (
                    <a href={selectedUrl} className="button-primary public-share-download" download>
                      <DownloadIcon />
                      {t("downloadSelected", { count: selected.size })}
                    </a>
                  ) : (
                    <button type="button" className="button-primary public-share-download" disabled>
                      <DownloadIcon />
                      {t("downloadSelected", { count: 0 })}
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
          {share.context ? <p className="public-share-eyebrow">{share.context}</p> : null}
          <h1 className="public-share-title">{share.name}</h1>
          <p className="public-share-meta muted">
            <span>{allImages ? t("photoCount", { count: share.files.length }) : t("fileCount", { count: share.files.length })}</span>
            {share.total_size_bytes > 0 ? <span>{formatFileSize(share.total_size_bytes)}</span> : null}
            {dateRange ? <span>{dateRange}</span> : null}
            {share.expires_at ? <span>{t("validUntil", { date: formatShortMonthDate(share.expires_at, locale) })}</span> : null}
          </p>
        </div>

        {share.files.length === 0 ? (
          <p className="muted">{t("noFiles")}</p>
        ) : (
          <ul className={selecting ? "public-share-masonry public-share-masonry-selecting" : "public-share-masonry"}>
            {share.files.map((file) => {
              const isSelected = selected.has(file.id);
              const ratio = file.width && file.height ? `${file.width} / ${file.height}` : undefined;
              return (
                <li key={file.id} className="public-share-tile-wrap">
                  <button
                    type="button"
                    className={isSelected ? "public-share-tile public-share-tile-selected" : "public-share-tile"}
                    onClick={() => (selecting ? toggle(file.id) : openFile(file))}
                    aria-pressed={selecting ? isSelected : undefined}
                    aria-label={selecting ? t("toggleSelect", { name: file.original_name }) : t("open", { name: file.original_name })}
                  >
                    {file.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={file.thumbnail_url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        className="public-share-tile-img"
                        style={ratio ? { aspectRatio: ratio } : undefined}
                      />
                    ) : (
                      <span className="public-share-tile-file">
                        <FileIcon />
                        <span className="public-share-tile-file-name">{file.original_name}</span>
                        <span className="muted">{formatFileSize(file.file_size_bytes)}</span>
                      </span>
                    )}
                    {selecting ? (
                      <span className="public-share-tile-check" aria-hidden="true">
                        {isSelected ? <CheckIcon /> : null}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </main>

      <footer className="public-share-footer">
        <div className="public-share-footer-inner">
          <p>{t("footerNotice")}</p>
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

      {viewerIndex !== null && images[viewerIndex] ? (
        <PublicShareViewer images={images} index={viewerIndex} onIndexChange={setViewerIndex} onClose={() => setViewerIndex(null)} />
      ) : null}
    </div>
  );
}

function PublicShareViewer({
  images,
  index,
  onIndexChange,
  onClose
}: {
  images: PublicShareFile[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}) {
  const t = useTranslations("share.publicPage");
  const rootRef = useRef<HTMLDivElement>(null);
  usePopupEscape(true, onClose, rootRef);
  usePopupScrollLock(true);

  const file = images[index];
  const hasPrev = index > 0;
  const hasNext = index < images.length - 1;
  const go = useCallback(
    (delta: number) => {
      const next = Math.min(Math.max(index + delta, 0), images.length - 1);
      if (next !== index) onIndexChange(next);
    },
    [images.length, index, onIndexChange]
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowLeft") go(-1);
      if (event.key === "ArrowRight") go(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div ref={rootRef} className="public-share-viewer" role="dialog" aria-modal="true" aria-label={file.original_name} onClick={onClose}>
      <div className="public-share-viewer-bar" onClick={(event) => event.stopPropagation()}>
        <div className="public-share-viewer-info">
          <strong title={file.original_name}>{file.original_name}</strong>
          <span>
            {t("position", { index: index + 1, total: images.length })}
            {file.file_size_bytes ? ` · ${formatFileSize(file.file_size_bytes)}` : null}
          </span>
        </div>
        <div className="public-share-viewer-actions">
          <a href={file.download_url} className="public-share-viewer-download" download>
            <DownloadIcon />
            {t("download")}
          </a>
          <button type="button" className="public-share-viewer-round" onClick={onClose} aria-label={t("close")}>
            <ActionIcon name="close" width={18} height={18} />
          </button>
        </div>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img key={file.id} src={file.view_url ?? ""} alt={file.original_name} className="public-share-viewer-img" onClick={(event) => event.stopPropagation()} />
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
    </div>,
    document.body
  );
}
