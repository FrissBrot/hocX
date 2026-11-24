"use client";

import type { Route } from "next";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { CaptureCorrectionMode, PhotoCaptureDateDialog } from "@/components/photos/photo-capture-date-dialog";
import { PhotosView } from "@/components/photos/photos-view";
import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import type {
  CaptureChangeBatch,
  CaptureChangeUndoResult,
  UploadCameraGroup,
  UploadJobDetail,
  UploadJobFileIds,
  UploadJobItem,
  UploadJobItemFile,
  UploadJobItemList,
} from "@/types/api";

import { actorLabel, reasonLabel, resultSummary, UploadItemStatusBadge, UploadStatusBadge, UploadsT } from "./upload-labels";

type Props = {
  area: "photos" | "files";
  job: UploadJobDetail;
  canManagePhotos: boolean;
  canShare: boolean;
  canManageSettings: boolean;
};

function refHref(job: UploadJobDetail): string | null {
  if (!job.ref) return null;
  if (job.ref.kind === "import") return "/files/import";
  if (job.ref.kind === "protocol" && job.ref.id) return `/protocols/${job.ref.id}`;
  return null;
}

function cameraLabel(camera: UploadCameraGroup, t: UploadsT): string {
  const name = [camera.camera_make, camera.camera_model].filter(Boolean).join(" ") || t("cameras.unknown");
  return camera.device_index ? t("cameras.device", { name, index: camera.device_index }) : name;
}

function offsetText(minutes: number, t: UploadsT): string {
  const absolute = Math.abs(minutes);
  return t("cameras.offset", { hours: Math.floor(absolute / 60), minutes: absolute % 60, direction: minutes < 0 ? "earlier" : "later" });
}

/** Vorgangsdetail: Zusammenfassung, Bezug, Optionen, Kameras und Reiter Fotos / Ergebnisliste /
 * Datumskorrekturen. Bulk-Aktionen laufen über die bestehenden, je Datei prüfenden Endpunkte. */
export function UploadJobDetailView({ area, job, canManagePhotos, canShare, canManageSettings }: Props) {
  const t = useTranslations("uploads");
  const locale = useLocale();
  const showToast = useToast();
  const showPhotos = (job.image_count ?? 0) > 0;
  const [tab, setTab] = useState(showPhotos ? "photos" : "results");
  const [selectionRequest, setSelectionRequest] = useState<{ key: number; ids: string[] } | null>(null);
  // Datumskorrektur aus dem Vorgang: Kamera verschieben, ganze Fotos des Vorgangs oder Auswahl der
  // Ergebnisliste auf ein festes Datum setzen («Datum setzen …», Rückgängig wie beim Verschieben)
  const [captureDialog, setCaptureDialog] = useState<{ ids: string[]; minutes: number | null; mode: CaptureCorrectionMode } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const options = job.options ?? {};
  const tags = Array.isArray(options.tags) ? (options.tags as string[]) : [];
  const href = refHref(job);

  async function cameraIds(camera: UploadCameraGroup): Promise<string[]> {
    const result = await browserApiFetch<UploadJobFileIds>(`/api/upload-jobs/${job.id}/file-ids?only_images=true&camera=${encodeURIComponent(camera.key)}`);
    return result?.file_ids ?? [];
  }

  async function openCaptureDialog(load: () => Promise<string[]>, mode: CaptureCorrectionMode, minutes: number | null = null) {
    try {
      const ids = await load();
      if (ids.length === 0) {
        showToast(t("setDate.none"), "info");
        return;
      }
      setCaptureDialog({ ids, minutes, mode });
    } catch {
      showToast(t("loadError"), "error");
    }
  }

  async function allImageIds(): Promise<string[]> {
    const result = await browserApiFetch<UploadJobFileIds>(`/api/upload-jobs/${job.id}/file-ids?only_images=true`);
    return result?.file_ids ?? [];
  }

  async function selectCamera(camera: UploadCameraGroup) {
    try {
      const ids = await cameraIds(camera);
      setTab("photos");
      setSelectionRequest({ key: Date.now(), ids });
    } catch {
      showToast(t("loadError"), "error");
    }
  }

  function shiftCamera(camera: UploadCameraGroup) {
    void openCaptureDialog(() => cameraIds(camera), "shift", camera.suggested_shift_minutes);
  }

  const tabs = [
    ...(showPhotos && canManagePhotos
      ? [{
          id: "photos",
          label: t("tabs.photos"),
          content: (
            <PhotosView
              key={reloadKey}
              uploadJobId={job.id}
              selectionRequest={selectionRequest}
              canManage={canManagePhotos}
              canShare={canShare}
              canManageSettings={canManageSettings}
            />
          ),
        }]
      : []),
    {
      id: "results",
      label: t("tabs.results"),
      count: job.counts.total,
      content: (
        <UploadJobItems
          key={reloadKey}
          jobId={job.id}
          selectable={canManagePhotos}
          onSetDate={(ids) => void openCaptureDialog(async () => ids, "set")}
        />
      ),
    },
    ...(showPhotos && canManagePhotos
      ? [{ id: "corrections", label: t("tabs.corrections"), content: <CaptureCorrections jobId={job.id} onUndone={() => setReloadKey((key) => key + 1)} /> }]
      : []),
  ];

  return (
    <div className="grid upload-job-detail">
      <div className="page-header">
        <div>
          <Link className="upload-history-back" href={`/${area}/uploads` as Route}>{t("backToHistory")}</Link>
          <h1 className="page-title">{t("detailTitle", { date: formatDateTime(job.created_at, locale) })}</h1>
          <p className="muted">{resultSummary(job, t)}</p>
        </div>
        <div className="table-toolbar-actions">
          {showPhotos && canManagePhotos ? (
            <button type="button" className="button-secondary" onClick={() => void openCaptureDialog(allImageIds, "set")}>
              {t("setDate.all")}
            </button>
          ) : null}
          <UploadStatusBadge status={job.status} />
        </div>
      </div>
      {job.reconstructed ? <StatusBanner tone="neutral" message={t("reconstructedHint")} /> : null}
      <section className="panel upload-job-facts" aria-label={t("factsLabel")}>
        <dl className="upload-job-facts-list">
          <div><dt>{t("column.person")}</dt><dd>{actorLabel(job, t)}</dd></div>
          <div><dt>{t("column.channel")}</dt><dd><Badge variant="neutral">{t(`channel.${job.channel}`)}</Badge></dd></div>
          {job.ref ? (
            <div>
              <dt>{t("column.ref")}</dt>
              <dd>
                {href ? <Link href={href as Route}>{job.ref.label ?? t(`ref.${job.ref.kind}`)}</Link> : job.ref.label ?? t(`ref.${job.ref.kind}`)}
                {job.ref.on_date ? ` · ${formatDate(job.ref.on_date)}` : null}
              </dd>
            </div>
          ) : null}
          {tags.length ? <div><dt>{t("options.tags")}</dt><dd>{tags.join(", ")}</dd></div> : null}
          {typeof options.estimated_taken_on === "string" ? <div><dt>{t("options.estimated")}</dt><dd>{formatDate(options.estimated_taken_on)}</dd></div> : null}
          {typeof options.include_gps === "boolean" ? <div><dt>{t("options.gps")}</dt><dd>{options.include_gps ? t("options.yes") : t("options.no")}</dd></div> : null}
          <div><dt>{t("files")}</dt><dd>{t("filesValue", { count: job.file_count })}</dd></div>
        </dl>
      </section>
      {job.cameras.length > 0 && canManagePhotos ? (
        <section className="upload-job-cameras" aria-label={t("cameras.title")}>
          <h2 className="section-title">{t("cameras.title")}</h2>
          <DataTable columns={[t("cameras.camera"), t("cameras.count"), t("cameras.period"), t("cameras.withTime"), t("cameras.actions")]}>
            {job.cameras.map((camera) => (
              <tr key={camera.key}>
                <td>
                  {cameraLabel(camera, t)}
                  {camera.suggested_shift_minutes !== null ? (
                    <span className="upload-camera-hint">{t("cameras.gpsHint", { offset: offsetText(camera.suggested_shift_minutes, t), samples: camera.suggestion_samples })}</span>
                  ) : null}
                </td>
                <td>{camera.count}</td>
                <td>{camera.earliest ? `${formatDateTime(camera.earliest, locale)} – ${formatDateTime(camera.latest, locale)}` : "–"}</td>
                <td>{t("cameras.withTimeValue", { count: camera.with_time, gps: camera.with_gps_time })}</td>
                <td className="upload-camera-actions">
                  <button type="button" className="button-secondary" onClick={() => void selectCamera(camera)}>{t("cameras.select")}</button>
                  <button type="button" className="button-secondary" onClick={() => shiftCamera(camera)}>{t("cameras.shift")}</button>
                  <button type="button" className="button-secondary" onClick={() => void openCaptureDialog(() => cameraIds(camera), "set")}>{t("cameras.setDate")}</button>
                </td>
              </tr>
            ))}
          </DataTable>
        </section>
      ) : null}
      <Tabs tabs={tabs} activeId={tab} onChange={setTab} />
      {captureDialog ? (
        <PhotoCaptureDateDialog
          open
          fileIds={captureDialog.ids}
          uploadJobId={job.id}
          initialMode={captureDialog.mode}
          initialShiftMinutes={captureDialog.minutes}
          onClose={() => setCaptureDialog(null)}
          onDone={() => setReloadKey((key) => key + 1)}
        />
      ) : null}
    </div>
  );
}

function FileState({ file }: { file: UploadJobItemFile | null }) {
  const t = useTranslations("uploads");
  if (!file) return null;
  if (file.state === "ok" && file.id) {
    return (
      <span className="upload-item-file">
        {file.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- Vorschaubild aus dem Backend, wie im Papierkorb
          <img className="upload-item-thumb" src={`${browserApiBaseUrl}${file.thumbnail_url}`} alt="" loading="lazy" />
        ) : null}
        <Link href={file.is_image ? `/photos?open=${file.id}` : `/files?open=${file.id}`}>{t("fileState.open")}</Link>
      </span>
    );
  }
  return <span className="muted">{t(`fileState.${file.state}`)}</span>;
}

/** Datei eines Items, die sich auswählen lässt (neu hochgeladen und noch vorhanden). */
export function selectableFileId(item: UploadJobItem): string | null {
  return item.status === "uploaded" && item.file?.state === "ok" && item.file.id ? item.file.id : null;
}

function UploadJobItems({ jobId, selectable, onSetDate }: { jobId: string; selectable: boolean; onSetDate: (ids: string[]) => void }) {
  const t = useTranslations("uploads");
  const showToast = useToast();
  const [items, setItems] = useState<UploadJobItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  async function load(next: number | null) {
    setLoading(true);
    try {
      const list = await browserApiFetch<UploadJobItemList>(`/api/upload-jobs/${jobId}/items?limit=100${next !== null ? `&cursor=${next}` : ""}`);
      setItems((current) => (next !== null ? [...current, ...(list?.items ?? [])] : list?.items ?? []));
      setCursor(list?.next_cursor ?? null);
    } catch {
      showToast(t("loadError"), "error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const selectableIds = selectable ? items.map(selectableFileId).filter((id): id is string => id !== null) : [];
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  function toggle(id: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  const columns = [t("items.name"), t("items.status"), t("items.reason"), t("items.size"), t("items.file")];
  return (
    <>
      {selected.size > 0 ? (
        <DataToolbar
          title={t("items.selectedCount", { count: selected.size })}
          actions={
            <>
              <button type="button" className="button-secondary" onClick={() => onSetDate([...selected])}>{t("setDate.selected")}</button>
              <button type="button" className="button-ghost" onClick={() => setSelected(new Set())}>{t("items.clearSelection")}</button>
            </>
          }
        />
      ) : null}
      <DataTable
        columns={
          selectableIds.length > 0
            ? [
                {
                  key: "select",
                  label: t("items.selectAll"),
                  header: (
                    <input
                      type="checkbox"
                      checked={allSelected}
                      aria-label={t("items.selectAll")}
                      onChange={(event) => setSelected(event.target.checked ? new Set(selectableIds) : new Set())}
                    />
                  ),
                },
                ...columns,
              ]
            : columns
        }
        emptyMessage={loading ? t("loading") : t("items.empty")}
      >
        {items.map((item) => {
          const fileId = selectableFileId(item);
          return (
          <tr key={item.id}>
            {selectableIds.length > 0 ? (
              <td>
                {fileId ? (
                  <input
                    type="checkbox"
                    checked={selected.has(fileId)}
                    aria-label={t("items.select", { name: item.name ?? fileId })}
                    onChange={(event) => toggle(fileId, event.target.checked)}
                  />
                ) : null}
              </td>
            ) : null}
            <td>{item.name ?? <span className="muted">{t("items.nameRemoved")}</span>}</td>
            <td>
              <UploadItemStatusBadge status={item.status} />
              {item.source === "client" ? <span className="muted upload-history-note">{t("items.browserReported")}</span> : null}
            </td>
            <td>
              {reasonLabel(item.reason_code, t) ?? "–"}
              {typeof item.reason_params.archive === "string" && item.reason_params.archive ? (
                <span className="muted upload-history-note">{t("items.fromArchive", { archive: item.reason_params.archive })}</span>
              ) : null}
            </td>
            <td>{item.size_bytes !== null ? formatFileSize(item.size_bytes) : "–"}</td>
            <td>
              {item.status === "duplicate" || item.status === "metadata_updated" ? (
                <FileState file={item.existing_file} />
              ) : (
                <FileState file={item.file} />
              )}
            </td>
          </tr>
          );
        })}
      </DataTable>
      {cursor !== null ? (
        <div className="load-more-row">
          <button type="button" className="button-secondary button-ghost" disabled={loading} onClick={() => void load(cursor)}>{t("loadMore")}</button>
        </div>
      ) : null}
    </>
  );
}

function CaptureCorrections({ jobId, onUndone }: { jobId: string; onUndone: () => void }) {
  const t = useTranslations("uploads");
  const locale = useLocale();
  const showToast = useToast();
  const [batches, setBatches] = useState<CaptureChangeBatch[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    browserApiFetch<CaptureChangeBatch[]>(`/api/capture-changes?upload_job_id=${jobId}`)
      .then((data) => setBatches(data ?? []))
      .catch(() => setBatches([]));
  }

  useEffect(load, [jobId]);

  async function undo(batch: CaptureChangeBatch) {
    setBusy(batch.id);
    try {
      const result = await browserApiFetch<CaptureChangeUndoResult>(`/api/capture-changes/${batch.id}/undo`, { method: "POST" });
      showToast(t("corrections.undone", { count: result?.restored_ids.length ?? 0 }), "success");
      if (result?.conflict_ids.length) showToast(t("corrections.conflicts", { count: result.conflict_ids.length }), "info");
      load();
      onUndone();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("corrections.undoError"), "error");
    } finally {
      setBusy(null);
    }
  }

  function describe(batch: CaptureChangeBatch): string {
    if (batch.mode === "set") {
      const at = typeof batch.params.corrected_at === "string" ? batch.params.corrected_at : null;
      if (!at) return t("corrections.modeSet");
      const day = formatDate(at.slice(0, 10));
      return t("corrections.modeSetTo", { date: batch.params.has_time ? `${day} ${at.slice(11, 16)}` : day });
    }
    if (batch.mode === "reset") return t("corrections.modeReset");
    const p = batch.params;
    const total = (((Number(p.shift_days ?? 0) * 24 + Number(p.shift_hours ?? 0)) * 60) + Number(p.shift_minutes ?? 0));
    return t("corrections.modeShift", { hours: Math.floor(Math.abs(total) / 60), minutes: Math.abs(total) % 60, direction: total < 0 ? "earlier" : "later" });
  }

  return (
    <DataTable
      columns={[t("corrections.when"), t("corrections.what"), t("corrections.who"), t("corrections.count"), t("corrections.action")]}
      emptyMessage={batches === null ? t("loading") : t("corrections.empty")}
    >
      {(batches ?? []).map((batch) => (
        <tr key={batch.id}>
          <td>{formatDateTime(batch.created_at, locale)}</td>
          <td>{describe(batch)}</td>
          <td>{batch.created_by_name ?? "–"}</td>
          <td>{t("corrections.countValue", { count: batch.updated_count, remaining: batch.remaining })}</td>
          <td>
            {batch.undone_at ? (
              <span className="muted">{t("corrections.undoneAt", { date: formatDateTime(batch.undone_at, locale) })}</span>
            ) : batch.can_undo ? (
              <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void undo(batch)}>{t("corrections.undo")}</button>
            ) : (
              <span className="muted">{t("corrections.noFiles")}</span>
            )}
          </td>
        </tr>
      ))}
    </DataTable>
  );
}
