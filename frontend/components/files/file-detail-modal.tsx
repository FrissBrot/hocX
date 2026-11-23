"use client";

import Link from "next/link";

// Datei-Detail (Design «hocX Datei-Detail Popup v2»): Kopf mit Name (umbenennen), Quelle, Status,
// Hochgeladen von und Version; links Vorschau (PDF-Ansicht/Text/Bild), rechts Reiter «Details &
// Tags» und «Verlauf»; Fuss mit Papierkorb (Bestätigung inline) und Öffnen/Teilen/Herunterladen.
import { FormEvent, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  DOCUMENT_STATUS_VARIANT,
  DocumentPreviewPane,
  DocumentStatusSection,
  DocumentVersionTimeline,
  PersonAvatar,
  shownVersion,
  useDocumentDetail,
} from "./document-panel";
import { FileTypeIcon } from "./file-type-icon";
import { ActionIcon } from "@/components/ui/action-icons";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { TagInput } from "@/components/ui/tag-input";
import { FileKeywords } from "./file-keywords";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/contexts/toast-context";
import { useDeferredPopupSave } from "@/lib/hooks/use-deferred-popup-save";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { fileDisplay, fileExtension } from "@/lib/files/display";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem, FileOverviewSource, FileTrashActionResult, StoredFileMetadata } from "@/types/api";

// Uebersetzt ueber den "files"-Namespace (source.*) - die Werte hier sind next-intl-Keys, kein
// fertiger Text, siehe Aufrufstellen (t("source." + SOURCE_KEY[item.source])).
const SOURCE_KEY: Record<FileOverviewSource, string> = {
  protocol_image: "protocol",
  word_import: "wordImport",
  submission_upload: "submission",
  gallery_upload: "upload",
  protocol_export: "protocolExport",
};

const SOURCE_BADGE_VARIANT: Record<FileOverviewSource, BadgeVariant> = {
  protocol_image: "info",
  word_import: "neutral",
  submission_upload: "success",
  gallery_upload: "warning",
  protocol_export: "info",
};

// Art der Originaldatei für «Word-Dokument · 17 KB» (Keys unter files.detail.kind.*).
const KIND_BY_EXTENSION: Record<string, string> = {
  doc: "word", docx: "word", odt: "word", rtf: "word",
  pdf: "pdf",
  xls: "spreadsheet", xlsx: "spreadsheet", ods: "spreadsheet", csv: "spreadsheet",
  ppt: "presentation", pptx: "presentation", odp: "presentation",
  txt: "text", md: "text",
  zip: "archive", rar: "archive", "7z": "archive", tar: "archive", gz: "archive",
};

function fileKind(name: string, mime: string | null): string {
  const kind = KIND_BY_EXTENSION[fileExtension(name)];
  if (kind) return kind;
  if (mime?.startsWith("image/")) return "image";
  if (mime?.startsWith("audio/")) return "audio";
  if (mime?.startsWith("video/")) return "video";
  return "file";
}

/** Eigene Tags der Dateien nach Häufigkeit (mindestens zweimal verwendet), häufigste zuerst. */
export function countFrequentTags(items: FileOverviewItem[], limit = 8): string[] {
  const counts = new Map<string, number>();
  for (const entry of items) for (const tag of entry.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([tag]) => tag);
}

// Frist des Papierkorbs (backend/app/core/trash_scope.py, TRASH_RETENTION).
const TRASH_RETENTION_DAYS = 30;

type TrashState = "idle" | "confirm" | "trashing" | "trashed" | "restoring";

export function FileDetailModal({
  item,
  tagSuggestions,
  frequentTags = [],
  onClose,
  onNavigate,
  onTagsSaved,
  onRenamed,
  onShare,
  onStep,
  position,
  canManage = false,
  onTrashed,
}: {
  item: FileOverviewItem;
  tagSuggestions: string[];
  /** «Häufig:» - die meistverwendeten Tags der geladenen Dateien, häufigste zuerst. */
  frequentTags?: string[];
  onClose: () => void;
  onNavigate: (href: string) => void;
  onTagsSaved: (tags: string[]) => void;
  /** Nach dem Umbenennen: neuer Anzeigename (mit Endung). */
  onRenamed?: (name: string) => void;
  /** «Link teilen» im Fuss. */
  onShare?: () => void;
  /** Blättern wie im Foto-Viewer (Pfeiltasten und Knöpfe): -1 zurück, +1 weiter. */
  onStep?: (direction: -1 | 1) => void;
  /** Stelle in der geladenen Liste, z. B. { index: 3, total: 40 } - fehlt, gibt es kein Blättern. */
  position?: { index: number; total: number };
  /** files.manage (Bilder: photos.manage): umbenennen und in den Papierkorb legen. */
  canManage?: boolean;
  /** Die Datei liegt im Papierkorb und das Popup verlässt sie (schliessen oder weiterblättern). */
  onTrashed?: (item: FileOverviewItem) => void;
}) {
  const t = useTranslations("files");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const showToast = useToast();
  const [metadata, setMetadata] = useState<StoredFileMetadata | null>(null);
  const [loadingMetadata, setLoadingMetadata] = useState(true);
  const [tagsValue, setTagsValue] = useState(item.tags.join(","));
  const { schedule, flush, saving, saveError } = useDeferredPopupSave();
  const [previewFailed, setPreviewFailed] = useState(false);
  const [tab, setTab] = useState("details");
  // Im Verlauf gewählte Version (null = aktuelle).
  const [versionId, setVersionId] = useState<string | null>(null);
  const [showMime, setShowMime] = useState(false);
  const [trash, setTrash] = useState<TrashState>("idle");
  const [trashedAt, setTrashedAt] = useState<number>(0);
  const documentState = useDocumentDetail(item.document);
  const detail = documentState.detail;
  const trashed = trash === "trashed" || trash === "restoring";
  const confirming = trash === "confirm" || trash === "trashing";

  useEffect(() => {
    setTagsValue(item.tags.join(","));
    setMetadata(null);
    setPreviewFailed(false);
    setLoadingMetadata(true);
    setVersionId(null);
    setShowMime(false);
    setTrash("idle");
    // Verspaetete Antworten einer vorher angezeigten Datei verwerfen (Audit MAIN-FE-007).
    let cancelled = false;
    browserApiFetch<StoredFileMetadata>(item.metadata_url)
      .then((data) => { if (!cancelled) setMetadata(data); })
      .catch(() => { if (!cancelled) setMetadata(null); })
      .finally(() => { if (!cancelled) setLoadingMetadata(false); });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  function handleTagsChange(value: string) {
    setTagsValue(value);
    const tags = value ? value.split(",").map((tag) => tag.trim()).filter(Boolean) : [];
    schedule(async () => {
      const saved = await browserApiFetch<string[]>(item.tags_url, { method: "PATCH", body: JSON.stringify({ tags }) });
      onTagsSaved(saved ?? tags);
    });
  }

  const currentTags = tagsValue ? tagsValue.split(",").map((tag) => tag.trim()).filter(Boolean) : [];
  const quickTags = frequentTags.filter((tag) => !currentTags.includes(tag) && tag !== item.origin_tag).slice(0, 4);

  async function leave() {
    if (!(await flush())) return;
    if (trashed) onTrashed?.(item);
    onClose();
  }

  const hasPrev = Boolean(onStep && position && position.index > 0);
  const hasNext = Boolean(onStep && position && position.index < position.total - 1);
  async function step(direction: -1 | 1) {
    if (!onStep || (direction < 0 ? !hasPrev : !hasNext)) return;
    // Offene Tag-Änderung zuerst speichern, sonst ginge sie beim Wechsel verloren
    if (!(await flush())) return;
    onStep(direction);
    // Erst nach dem Wechsel aus der Liste nehmen, sonst stimmt die Stelle nicht mehr
    if (trashed) onTrashed?.(item);
  }

  // Blättern mit Pfeil links/rechts bzw. J/L (Registry `media.previous`/`media.next`, wie im
  // Foto-Viewer). Der Dispatcher lässt Tippen (Tag-Feld, Umbenennen), Menüs/Listen und darüber
  // liegende Rückfragen aussen vor; am Rand ist die Bindung «nicht zuständig».
  const detailRef = useRef<HTMLDivElement>(null);
  useShortcut("media.previous", () => (hasPrev ? void step(-1) : false), { scopeRef: detailRef, enabled: Boolean(onStep) });
  useShortcut("media.next", () => (hasNext ? void step(1) : false), { scopeRef: detailRef, enabled: Boolean(onStep) });

  async function moveToTrash() {
    setTrash("trashing");
    try {
      const result = await browserApiFetch<FileTrashActionResult>("/api/files/trash", { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
      if (result && result.file_ids.length > 0) {
        setTrash("trashed");
        setTrashedAt(Date.now());
        showToast(t("trash.movedToast", { name: item.original_name }), "success");
        return;
      }
      setTrash("idle");
      showToast(result?.errors.join(" · ") || t("trash.actionError"), "error");
    } catch (error) {
      setTrash("idle");
      showToast(error instanceof Error ? error.message : t("trash.actionError"), "error");
    }
  }

  async function restore() {
    setTrash("restoring");
    try {
      const result = await browserApiFetch<FileTrashActionResult>("/api/files/trash/restore", { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
      if (result && result.file_ids.length > 0) {
        setTrash("idle");
        showToast(t("trash.restoredToast", { name: item.original_name }), "success");
        return;
      }
      setTrash("trashed");
      showToast(result?.errors.join(" · ") || t("trash.actionError"), "error");
    } catch (error) {
      setTrash("trashed");
      showToast(error instanceof Error ? error.message : t("trash.actionError"), "error");
    }
  }

  const display = fileDisplay(item);
  const isImage = Boolean(item.mime_type?.startsWith("image/")) && !previewFailed;
  const version = shownVersion(detail, versionId);
  const versionCount = detail?.versions.length ?? item.document?.version_count ?? 0;
  const fileUrl = `${browserApiBaseUrl}${item.content_url}`;
  const pdf = version?.pdf ?? null;
  const original = version?.original ?? null;
  const openUrl = pdf ? `${browserApiBaseUrl}${pdf.url}` : original ? `${browserApiBaseUrl}${original.url}` : fileUrl;
  const downloadHref = pdf
    ? `${browserApiBaseUrl}${pdf.download_url}`
    : original ? `${browserApiBaseUrl}${original.download_url}` : fileUrl;
  const originalName = original?.name ?? item.original_name;
  const originalExt = fileExtension(originalName).toUpperCase();
  const originalMime = original?.mime_type ?? item.mime_type;
  const originalSize = original?.size_bytes ?? item.file_size_bytes;
  const dimensions = metadata?.width && metadata?.height ? `${metadata.width} × ${metadata.height} px` : null;
  const uploader = metadata?.uploaded_by_name ?? null;
  const deletable = item.source === "gallery_upload";
  const restoreUntil = new Date(trashedAt + TRASH_RETENTION_DAYS * 86_400_000).toISOString();

  const navigation = onStep && position && position.total > 1 ? (
    <div className="file-detail-nav">
      <button type="button" className="button-icon-soft" aria-label={t("detail.previousFile")} title={t("detail.previousFile")} disabled={!hasPrev} onClick={() => void step(-1)}>‹</button>
      <span className="file-detail-nav-count">{t("detail.position", { index: position.index + 1, total: position.total })}</span>
      <button type="button" className="button-icon-soft" aria-label={t("detail.nextFile")} title={t("detail.nextFile")} disabled={!hasNext} onClick={() => void step(1)}>›</button>
    </div>
  ) : undefined;

  const header = (
    <div className="file-detail-head">
      <FileTypeIcon name={display.name} extension={display.extension} />
      <div className="file-detail-head-main">
        <FileTitle
          item={item}
          name={display.name}
          canRename={canManage && !trashed}
          onRenamed={(name) => onRenamed?.(name)}
        />
        <div className="file-detail-head-meta">
          <Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{t(`source.${SOURCE_KEY[item.source]}`)}</Badge>
          {item.document ? (
            <Badge variant={DOCUMENT_STATUS_VARIANT[detail?.status ?? item.document.status]} dot>
              {t(`document.statusLabel.${detail?.status ?? item.document.status}`)}
            </Badge>
          ) : null}
          {uploader ? (
            <span className="file-detail-person">
              {t("detail.uploadedByPrefix")}
              <PersonAvatar name={uploader} />
              <strong>{uploader}</strong>
            </span>
          ) : null}
          {metadata?.upload_job ? (
            <Link className="file-detail-upload-job" href={`/${item.is_image ? "photos" : "files"}/uploads/${metadata.upload_job.id}`}>
              {t(metadata.upload_job.reconstructed ? "detail.uploadJobLinkReconstructed" : "detail.uploadJobLink", { count: metadata.upload_job.uploaded_count })}
            </Link>
          ) : null}
          {version ? (
            <span className="muted">
              {versionCount > 1
                ? t("detail.versionOf", { current: version.version_number, total: versionCount })
                : t("document.versionNumber", { number: version.version_number })}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );

  const footer = (
    <div className={`file-detail-footer${confirming ? " file-detail-footer-confirm" : ""}`}>
      {confirming ? (
        <TrashConfirm versions={versionCount} busy={trash === "trashing"} onCancel={() => setTrash("idle")} onConfirm={() => void moveToTrash()} />
      ) : (
        <>
          <div className="file-detail-footer-start">
            {trashed ? null : deletable && canManage ? (
              <button type="button" className="button-danger" onClick={() => setTrash("confirm")}>
                <ActionIcon name="delete" /> {t("trash.moveLabel")}
              </button>
            ) : (
              <span className="file-detail-lock-hint">
                <ActionIcon name="lock" />
                {!deletable
                  ? t(item.source === "submission_upload" ? "detail.trashHintSubmission" : "detail.trashHintProtocol")
                  : t("detail.trashHintPermission")}
              </span>
            )}
          </div>
          <div className="modal-footer-actions file-detail-footer-actions">
            {onShare && !trashed ? (
              <button type="button" className="button-secondary" onClick={onShare}><ActionIcon name="link" /> {t("detail.shareLink")}</button>
            ) : null}
            {pdf ? <a href={openUrl} target="_blank" rel="noreferrer" className="button-secondary">{t("detail.openNewTab")}</a> : null}
            <a href={downloadHref} download className="button-primary">
              {pdf ? t("document.downloadPdf") : t("detail.downloadOriginalShort")}
            </a>
          </div>
        </>
      )}
    </div>
  );

  const detailsContent = (
    <div className="file-detail-meta-stack">
      <section className="file-detail-section file-detail-tags">
        <h3 className="file-detail-section-title">
          {t("detail.tagsTitle")}
          <span className={saving ? "file-detail-saving" : "file-detail-saved"}>{saving ? t("detail.saving") : t("detail.autoSaved")}</span>
        </h3>
        <span className="tag-chip tag-chip-sm tag-chip-origin" title={t("detail.originLocked")}>
          <ActionIcon name="lock" />
          {item.origin_tag}
        </span>
        <TagInput value={tagsValue} onChange={handleTagsChange} suggestions={tagSuggestions} placeholder={t("detail.tagPlaceholder")} readOnly={trashed || !canManage} offerCreate />
        {quickTags.length > 0 && !trashed && canManage ? (
          <div className="file-detail-quick-tags">
            <span className="muted">{t("detail.frequentTags")}</span>
            {quickTags.map((tag) => (
              <button key={tag} type="button" className="file-detail-quick-tag" onClick={() => handleTagsChange([...currentTags, tag].join(","))}>
                <ActionIcon name="add" /> {tag}
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <FileKeywords fileId={item.id} readOnly={trashed || !canManage} className="file-detail-section" titleClassName="file-detail-section-title" />

      {item.document ? (
        <DocumentStatusSection detail={detail} versionId={versionId} scanStatus={item.scan_status} onReload={documentState.reload} />
      ) : null}

      <section className="file-detail-section">
        <h3 className="file-detail-section-title">{t("detail.detailsTitle")}</h3>
        <dl className="file-detail-meta-list">
          {item.ref_label ? (
            <div>
              <dt>{t("detail.reference")}</dt>
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
          ) : null}
          {item.element_label ? (
            <div>
              <dt>{t("detail.submissionElement")}</dt>
              <dd>
                {item.element_label}
                {item.element_date ? <span className="muted"> · {formatDate(item.element_date)}</span> : null}
              </dd>
            </div>
          ) : null}
          <div>
            <dt>{t("detail.uploadedAt")}</dt>
            <dd className="file-detail-person">
              {uploader ? <><PersonAvatar name={uploader} />{uploader}<span className="muted"> · </span></> : null}
              <span className={uploader ? "muted" : undefined}>{formatDateTime(item.created_at, locale)}</span>
            </dd>
          </div>
          <div>
            <dt>{t("detail.original")}</dt>
            <dd>
              {[t(`detail.kind.${fileKind(originalName, originalMime)}`), formatFileSize(originalSize, locale) || null].filter(Boolean).join(" · ")}
              {originalMime ? (
                <button type="button" className="file-detail-link file-detail-mime-toggle" aria-expanded={showMime} onClick={() => setShowMime((open) => !open)}>
                  {showMime ? t("detail.mimeHide") : t("detail.mimeType")}
                </button>
              ) : null}
              {showMime && originalMime ? <code className="file-detail-mime">{originalMime}</code> : null}
            </dd>
          </div>
          {item.mime_type?.startsWith("image/") ? (
            <div>
              <dt>{t("detail.dimensions")}</dt>
              <dd className={loadingMetadata ? "muted" : undefined}>{loadingMetadata ? t("detail.loading") : dimensions ?? t("detail.unknown")}</dd>
            </div>
          ) : null}
        </dl>
        {pdf && original && originalMime !== "application/pdf" ? (
          <a href={`${browserApiBaseUrl}${original.download_url}`} download className="button-secondary button-ghost file-detail-download-original">
            <ActionIcon name="download" /> {t("menu.downloadOriginal", { ext: originalExt })}
          </a>
        ) : null}
      </section>
    </div>
  );

  return (
    <Modal
      open
      title={display.name}
      onEscape={leave}
      onClose={() => void leave()}
      size="wide"
      className="file-detail-modal"
      header={header}
      headerActions={navigation}
      footer={trashed ? undefined : footer}
    >
      {saveError ? <StatusBanner tone="error" message={saveError} /> : null}
      <div className="file-detail" ref={detailRef}>
        <div className="file-detail-preview-col">
          {item.document ? (
            <DocumentPreviewPane
              detail={detail}
              loadFailed={documentState.loadFailed}
              versionId={versionId}
              onShowCurrent={() => setVersionId(null)}
              name={display.name}
              scanStatus={item.scan_status}
              originalUrl={item.content_url}
            />
          ) : (
            <div className="file-detail-preview">
              <a href={fileUrl} target="_blank" rel="noreferrer" className={isImage ? "file-detail-preview-link" : "file-detail-preview-icon"}>
                {isImage ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={fileUrl} alt={item.original_name} className="file-detail-preview-img" onError={() => setPreviewFailed(true)} />
                ) : (
                  <>
                    <span className="file-detail-preview-glyph">
                      <FileTypeIcon name={item.original_name} />
                    </span>
                    <span className="file-detail-preview-cta">{t("detail.openOriginal")}</span>
                  </>
                )}
              </a>
            </div>
          )}
        </div>

        <div className="file-detail-meta">
          {item.document ? (
            <Tabs
              activeId={tab}
              onChange={setTab}
              tabs={[
                { id: "details", label: t("detail.tabDetails"), content: detailsContent },
                {
                  id: "history",
                  label: t("detail.tabHistory"),
                  count: versionCount,
                  content: <DocumentVersionTimeline detail={detail} versionId={versionId} onSelect={setVersionId} />,
                },
              ]}
            />
          ) : (
            detailsContent
          )}
        </div>

        {trashed ? (
          <div className="file-detail-trashed" role="status">
            <span className="file-detail-trashed-icon" aria-hidden="true"><ActionIcon name="delete" /></span>
            <h3>{t("detail.trashedTitle")}</h3>
            <p className="muted">{t("detail.trashedText", { name: display.name, date: formatDate(restoreUntil) })}</p>
            <div className="file-detail-trashed-actions">
              <button type="button" className="button-secondary" onClick={() => void restore()} disabled={trash === "restoring"}>{t("trash.restore")}</button>
              {hasNext ? (
                <button type="button" className="button-primary" onClick={() => void step(1)}>{t("detail.nextFileAction")}</button>
              ) : (
                <button type="button" className="button-primary" onClick={() => void leave()}>{tCommon("close")}</button>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

/** Dateiname im Kopf; mit Recht ein Klick zum Umbenennen (Endung bleibt fest). */
function FileTitle({
  item,
  name,
  canRename,
  onRenamed,
}: {
  item: FileOverviewItem;
  name: string;
  canRename: boolean;
  onRenamed: (name: string) => void;
}) {
  const t = useTranslations("files");
  const showToast = useToast();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const extension = fileExtension(item.original_name);
  const base = extension ? item.original_name.slice(0, -(extension.length + 1)) : item.original_name;

  useEffect(() => setEditing(false), [item.id]);
  // Esc bricht nur das Umbenennen ab, nicht das ganze Popup.
  usePopupEscape(editing, () => setEditing(false), formRef);

  function start() {
    setValue(base);
    setEditing(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const next = value.trim();
    if (!next || next === base) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      const result = await browserApiFetch<{ original_name: string }>(`/api/stored-files/${item.id}/name`, {
        method: "PATCH",
        body: JSON.stringify({ name: extension ? `${next}.${extension}` : next }),
      });
      onRenamed(result?.original_name ?? next);
      showToast(t("detail.renamedToast"), "success");
      setEditing(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("detail.renameError"), "error");
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <form ref={formRef} className="file-detail-rename" onSubmit={(event) => void save(event)}>
        <input
          className="file-detail-rename-input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          aria-label={t("detail.renameLabel")}
          maxLength={200}
          autoFocus
          onFocus={(event) => event.currentTarget.select()}
        />
        {extension ? <span className="file-detail-rename-ext">.{extension}</span> : null}
        <button type="button" className="button-ghost" onClick={() => setEditing(false)} disabled={busy}>{t("detail.cancel")}</button>
        <button type="submit" className="button-primary" disabled={busy || !value.trim()}>{t("detail.renameSave")}</button>
      </form>
    );
  }
  if (!canRename) return <h2 className="file-detail-title">{name}</h2>;
  return (
    <h2 className="file-detail-title">
      <button type="button" className="file-detail-title-button" title={t("detail.renameHint")} onClick={start}>
        {name}
        <ActionIcon name="edit" />
      </button>
    </h2>
  );
}

function TrashConfirm({ versions, busy, onCancel, onConfirm }: { versions: number; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const t = useTranslations("files");
  const ref = useRef<HTMLDivElement>(null);
  usePopupEscape(!busy, onCancel, ref);
  return (
    <div className="file-detail-confirm" ref={ref} role="alert">
      <span className="file-detail-confirm-icon" aria-hidden="true"><ActionIcon name="delete" /></span>
      <span className="file-detail-confirm-text">
        <strong>{t("detail.trashConfirm")}</strong>
        <span>{t("detail.trashConfirmHint", { count: versions, days: TRASH_RETENTION_DAYS })}</span>
      </span>
      <div className="modal-footer-actions">
        <button type="button" className="button-ghost" onClick={onCancel} disabled={busy}>{t("detail.cancel")}</button>
        <button type="button" className="button-danger" onClick={onConfirm} disabled={busy} autoFocus>{t("trash.moveLabel")}</button>
      </div>
    </div>
  );
}

export { SOURCE_KEY, SOURCE_BADGE_VARIANT };
