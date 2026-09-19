"use client";

import { useEffect, useRef, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem, FileOverviewSource, StoredFileMetadata } from "@/types/api";

const SOURCE_LABEL: Record<FileOverviewSource, string> = {
  protocol_image: "Protokoll",
  word_import: "Word-Import",
  submission_upload: "Abgabe",
  gallery_upload: "Upload",
};

const SOURCE_BADGE_VARIANT: Record<FileOverviewSource, BadgeVariant> = {
  protocol_image: "info",
  word_import: "neutral",
  submission_upload: "success",
  gallery_upload: "warning",
};

export function FileDetailModal({
  item,
  tagSuggestions,
  onClose,
  onNavigate,
  onTagsSaved,
}: {
  item: FileOverviewItem;
  tagSuggestions: string[];
  onClose: () => void;
  onNavigate: (href: string) => void;
  onTagsSaved: (tags: string[]) => void;
}) {
  const [metadata, setMetadata] = useState<StoredFileMetadata | null>(null);
  const [loadingMetadata, setLoadingMetadata] = useState(true);
  const [tagsValue, setTagsValue] = useState(item.tags.join(","));
  const [saving, setSaving] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;

  useEffect(() => {
    setTagsValue(item.tags.join(","));
    setMetadata(null);
    setPreviewFailed(false);
    setLoadingMetadata(true);
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => setMetadata(data))
      .catch(() => setMetadata(null))
      .finally(() => setLoadingMetadata(false));
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
        const saved = await browserApiFetch<string[]>(item.tags_url, {
          method: "PATCH",
          body: JSON.stringify({ tags }),
        });
        onTagsSaved(saved ?? tags);
      } finally {
        setSaving(false);
      }
    }, 500);
  }

  const dimensions = metadata?.width && metadata?.height ? `${metadata.width} × ${metadata.height} px` : null;
  const extension = fileExtension(item.original_name);
  const isImage = Boolean(item.mime_type?.startsWith("image/")) && !previewFailed;

  return (
    <Modal open title={item.original_name} onClose={onClose} size="wide" className="file-detail-modal">
      <div className="file-detail">
        <div className="file-detail-preview">
          <a href={fileUrl} target="_blank" rel="noreferrer" className={isImage ? "file-detail-preview-link" : "file-detail-preview-icon"}>
            {isImage ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={fileUrl} alt={item.original_name} className="file-detail-preview-img" onError={() => setPreviewFailed(true)} />
            ) : (
              <>
                <span className="file-detail-preview-glyph">
                  <FileTypeIcon />
                  {extension ? <span className="file-detail-preview-ext">{extension}</span> : null}
                </span>
                <span className="file-detail-preview-cta">Original öffnen</span>
              </>
            )}
          </a>
        </div>

        <div className="file-detail-meta">
          <section className="file-detail-section">
            <h3 className="file-detail-section-title">Details</h3>
            <dl className="file-detail-meta-list">
              <div>
                <dt>Quelle</dt>
                <dd><Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{SOURCE_LABEL[item.source]}</Badge></dd>
              </div>
              {item.ref_label && (
                <div>
                  <dt>Bezug</dt>
                  <dd className="file-detail-ref">
                    {item.ref_href ? (
                      <button type="button" className="file-card-ref" onClick={() => onNavigate(item.ref_href!)}>
                        {item.ref_label}
                      </button>
                    ) : (
                      item.ref_label
                    )}
                    {item.ref_date ? <span className="muted"> · {formatDate(item.ref_date)}</span> : null}
                  </dd>
                </div>
              )}
              <div>
                <dt>Hochgeladen</dt>
                <dd>{formatDateTime(item.created_at)}</dd>
              </div>
              {metadata?.uploaded_by_name && (
                <div>
                  <dt>Hochgeladen von</dt>
                  <dd>{metadata.uploaded_by_name}</dd>
                </div>
              )}
              <div>
                <dt>Dateityp</dt>
                <dd>{item.mime_type ?? "Unbekannt"}</dd>
              </div>
              {item.file_size_bytes ? (
                <div>
                  <dt>Grösse</dt>
                  <dd>{formatFileSize(item.file_size_bytes)}</dd>
                </div>
              ) : null}
              {loadingMetadata ? (
                <div>
                  <dt>Bildmasse</dt>
                  <dd className="muted">Lädt…</dd>
                </div>
              ) : dimensions ? (
                <div>
                  <dt>Bildmasse</dt>
                  <dd>{dimensions}</dd>
                </div>
              ) : null}
            </dl>
          </section>

          <section className="file-detail-section">
            <h3 className="file-detail-section-title">Herkunft</h3>
            <span className="tag-chip tag-chip-sm tag-chip-origin">{item.origin_tag}</span>
          </section>

          <section className="file-detail-section file-detail-tags">
            <h3 className="file-detail-section-title">
              Tags {saving ? <span className="file-detail-saving">Speichert…</span> : null}
            </h3>
            <TagInput value={tagsValue} onChange={handleTagsChange} suggestions={tagSuggestions} placeholder="Tag hinzufügen…" />
          </section>

          <a href={fileUrl} target="_blank" rel="noreferrer" className="button-secondary button-ghost file-detail-open">
            Original in neuem Tab öffnen
          </a>
        </div>
      </div>
    </Modal>
  );
}

function fileExtension(name: string): string | null {
  const dot = name.lastIndexOf(".");
  if (dot < 0 || dot === name.length - 1) return null;
  return name.slice(dot + 1, dot + 6).toUpperCase();
}

function FileTypeIcon() {
  return (
    <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export { SOURCE_LABEL, SOURCE_BADGE_VARIANT };
