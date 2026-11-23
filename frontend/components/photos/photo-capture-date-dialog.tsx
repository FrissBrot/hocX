"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { StatusBanner } from "@/components/ui/status-banner";
import { TimeInput } from "@/components/ui/time-input";
import { todayIso } from "@/components/mobile/mobile-utils";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { runInChunks } from "@/lib/uploads/upload-jobs";
import { formatDate } from "@/lib/utils/format";
import {
  CaptureChangeUndoResult,
  FileBulkCaptureDatePreview,
  FileBulkCaptureDateResult,
  FileOverviewItem,
  StoredFileMetadata,
} from "@/types/api";

// Korrigiertes Aufnahmedatum (Backend: capture_date.py, Migration 0200). Hat Vorrang vor EXIF und
// Schätzung; das EXIF-Datum bleibt gespeichert und die Korrektur lässt sich wieder entfernen.
// Upload-Verlauf (1.6): Verschieben um Tage, Stunden und Minuten mit Richtung (früher/später) oder
// nach einem Referenzfoto, Vorschau auf dem Server, Stückelung grosser Auswahlen und «Rückgängig».

// Ein Aufruf des Backends verarbeitet höchstens so viele Bilder (MAX_CAPTURE_DATE_BULK in
// schemas/files.py); grössere Auswahlen teilt der Dialog in Stücke mit derselben Korrektur (batch_id).
export const MAX_CAPTURE_DATE_BULK = 500;
// Obergrenze einer Auswahl im Dialog (wie GET /upload-jobs/{id}/file-ids)
export const MAX_CAPTURE_DATE_SELECTION = 10_000;

export type CaptureCorrectionMode = "set" | "shift" | "reset";

export type CaptureCorrectionRequest =
  | { mode: "set"; date: string; time: string }
  | { mode: "shift"; days: number; hours: number; minutes?: number; seconds?: number }
  | { mode: "reset" };

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function totalSeconds(days: number, hours: number, minutes = 0, seconds = 0): number {
  return ((days * 24 + hours) * 60 + minutes) * 60 + seconds;
}

/** Versatz als Text («1 Tag, 2 Stunden und 15 Minuten») mit Richtung; gemischte Vorzeichen werden
 * zuerst zu einer Gesamtdauer verrechnet. */
export function describeOffset(days: number, hours: number, t: TFunc, minutes = 0, seconds = 0): { offset: string; direction: "earlier" | "later" } {
  const total = totalSeconds(days, hours, minutes, seconds);
  let rest = Math.abs(total);
  const wholeDays = Math.floor(rest / 86_400);
  rest -= wholeDays * 86_400;
  const restHours = Math.floor(rest / 3_600);
  rest -= restHours * 3_600;
  const restMinutes = Math.floor(rest / 60);
  const restSeconds = rest - restMinutes * 60;
  const parts = [
    wholeDays ? t("offsetDays", { count: wholeDays }) : null,
    restHours ? t("offsetHours", { count: restHours }) : null,
    restMinutes ? t("offsetMinutes", { count: restMinutes }) : null,
    restSeconds ? t("offsetSeconds", { count: restSeconds }) : null,
  ].filter((part): part is string => Boolean(part));
  const offset = parts.length <= 1 ? parts.join("") : `${parts.slice(0, -1).join(", ")} ${t("offsetAnd")} ${parts[parts.length - 1]}`;
  return { offset, direction: total < 0 ? "earlier" : "later" };
}

/** Ganze Tage des Gesamtversatzes, gegen null gerundet - wie das Backend
 * (`image_metadata_service.whole_shift_days`): Bei Fotos ohne Uhrzeit wirkt nur dieser Teil
 * (−13 h → 0, 1 Tag − 2 h → 0, −30 h → −1). */
export function wholeShiftDays(days: number, hours: number, minutes = 0, seconds = 0): number {
  return Math.trunc(totalSeconds(days, hours, minutes, seconds) / 86_400) || 0; // kein -0
}

/** Hinweis für Fotos ohne Uhrzeit, wenn der Versatz mehr als ganze Tage enthält: null bei reinen Tagen. */
export function noTimeShiftNote(days: number, hours: number, t: TFunc, minutes = 0, seconds = 0): string | null {
  if (totalSeconds(days, hours, minutes, seconds) % 86_400 === 0) return null;
  return t("shiftNoTimeNote", { days: Math.abs(wholeShiftDays(days, hours, minutes, seconds)) });
}

/** Vorzeichenbehafteter Versatz (Sekunden) in Felder zerlegt (alle mit demselben Vorzeichen). */
export function splitOffset(total: number): { days: number; hours: number; minutes: number; seconds: number } {
  const sign = total < 0 ? -1 : 1;
  let rest = Math.abs(Math.round(total));
  const days = Math.floor(rest / 86_400);
  rest -= days * 86_400;
  const hours = Math.floor(rest / 3_600);
  rest -= hours * 3_600;
  const minutes = Math.floor(rest / 60);
  const seconds = rest - minutes * 60;
  const signed = (value: number) => (value === 0 ? 0 : sign * value);
  return { days: signed(days), hours: signed(hours), minutes: signed(minutes), seconds: signed(seconds) };
}

export function captureCorrectionPayload(request: CaptureCorrectionRequest) {
  if (request.mode === "set") return { mode: "set", corrected_date: request.date, corrected_time: request.time || null };
  if (request.mode === "shift") {
    return {
      mode: "shift",
      shift_days: request.days,
      shift_hours: request.hours,
      ...(request.minutes ? { shift_minutes: request.minutes } : {}),
      ...(request.seconds ? { shift_seconds: request.seconds } : {}),
    };
  }
  return { mode: "reset" };
}

/** Bestätigung mit Hinweis (Reihenfolge im Zeitstrahl, Termin-Zuordnung, Original bleibt
 * erhalten, Anzahl Bilder) - für die Einzelbearbeitung im Viewer und die Mehrfachauswahl. */
export function useCaptureCorrectionConfirm() {
  const t = useTranslations("photos.captureCorrection");
  const confirm = useConfirm();
  return (request: CaptureCorrectionRequest, count: number) => {
    let message: string;
    if (request.mode === "set") {
      const date = request.time ? t("dateWithTime", { date: formatDate(request.date), time: request.time }) : formatDate(request.date);
      message = t("confirmSet", { count, date });
    } else if (request.mode === "shift") {
      message = t("confirmShift", { count, ...describeOffset(request.days, request.hours, t, request.minutes ?? 0, request.seconds ?? 0) });
      const note = noTimeShiftNote(request.days, request.hours, t, request.minutes ?? 0, request.seconds ?? 0);
      if (note) message = `${message} ${note}`;
    } else {
      message = t("confirmReset", { count });
    }
    return confirm({ title: t("confirmTitle"), message, confirmLabel: t("confirmLabel") });
  };
}

/** Nicht negative Ganzzahl aus einem Feld («» = 0), sonst null (ungültig). */
function parseAmount(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return 0;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

/** Kamerazeit eines Fotos (Ziffern des ISO-Werts, ohne Zeitzone) in Sekunden seit 1970, null ohne Uhrzeit. */
export function cameraSeconds(metadata: Pick<StoredFileMetadata, "capture_corrected_at" | "capture_corrected_has_time" | "exif_taken_at">): number | null {
  const value = metadata.capture_corrected_at
    ? metadata.capture_corrected_has_time ? metadata.capture_corrected_at : null
    : metadata.exif_taken_at;
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(value);
  if (!match) return null;
  const [, y, m, d, hh, mm, ss] = match;
  return Date.UTC(Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm), Number(ss ?? 0)) / 1000;
}

function inputSeconds(date: string, time: string): number | null {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const timeMatch = /^(\d{2}):(\d{2})$/.exec(time);
  if (!dateMatch || !timeMatch) return null;
  return Date.UTC(Number(dateMatch[1]), Number(dateMatch[2]) - 1, Number(dateMatch[3]), Number(timeMatch[1]), Number(timeMatch[2])) / 1000;
}

function formatMoment(value: string | null, hasTime: boolean): string {
  if (!value) return "–";
  const date = formatDate(value.slice(0, 10));
  return hasTime ? `${date} ${value.slice(11, 16)}` : date;
}

type ShiftKind = "offset" | "reference";
type ReferenceSource = "time" | "photo";

function mergePreview(previews: FileBulkCaptureDatePreview[]): FileBulkCaptureDatePreview | null {
  if (previews.length === 0) return null;
  const sum = (key: keyof FileBulkCaptureDatePreview) => previews.reduce((total, preview) => total + (preview[key] as number), 0);
  return {
    will_change: sum("will_change"), unchanged: sum("unchanged"), no_date: sum("no_date"),
    date_only_unchanged: sum("date_only_unchanged"), date_only_changed: sum("date_only_changed"), invalid: sum("invalid"),
    not_found: sum("not_found"), not_image: previews.reduce((total, preview) => total + (preview.not_image ?? 0), 0), no_date_ids: previews.flatMap((preview) => preview.no_date_ids).slice(0, MAX_CAPTURE_DATE_BULK),
    samples: previews.flatMap((preview) => preview.samples).slice(0, 20), day_changes: sum("day_changes"),
    event_changes: sum("event_changes"), event_transitions: previews.flatMap((preview) => preview.event_transitions).slice(0, 10),
  };
}

/** Mehrfachauswahl der Galerie bzw. eines Upload-Vorgangs: «Aufnahmedatum ändern» für alle gewählten Bilder. */
export function PhotoCaptureDateDialog({
  open,
  fileIds,
  onClose,
  onDone,
  uploadJobId,
  referenceItems = [],
  initialShiftMinutes,
  initialMode,
}: {
  open: boolean;
  fileIds: string[];
  onClose: () => void;
  onDone: () => void;
  /** Upload-Verlauf: Korrektur gehört zu diesem Vorgang (Reiter «Datumskorrekturen»). */
  uploadJobId?: string;
  /** Geladene Fotos für «Nach Referenzfoto» (Auswahl und Foto einer anderen Kamera). */
  referenceItems?: FileOverviewItem[];
  /** Vorschlag (z. B. aus der GPS-Zeit einer Kamera), in Minuten, vorzeichenbehaftet. */
  initialShiftMinutes?: number | null;
  /** Upload-Verlauf «Datum setzen …»: Dialog im passenden Modus öffnen. */
  initialMode?: CaptureCorrectionMode;
}) {
  const t = useTranslations("photos.captureCorrection");
  const showToast = useToast();
  const confirmCorrection = useCaptureCorrectionConfirm();
  const suggested = initialShiftMinutes ? splitOffset(initialShiftMinutes * 60) : null;
  const [mode, setMode] = useState<CaptureCorrectionMode>(initialMode ?? (suggested ? "shift" : "set"));
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [shiftKind, setShiftKind] = useState<ShiftKind>("offset");
  const [direction, setDirection] = useState<"earlier" | "later">((initialShiftMinutes ?? 0) < 0 ? "earlier" : "later"); // i18n-ok: Vergleich, kein Text
  const [days, setDays] = useState(suggested ? String(Math.abs(suggested.days)) : "0");
  const [hours, setHours] = useState(suggested ? String(Math.abs(suggested.hours)) : "0");
  const [minutes, setMinutes] = useState(suggested ? String(Math.abs(suggested.minutes)) : "0");
  const [referenceId, setReferenceId] = useState("");
  const [referenceSource, setReferenceSource] = useState<ReferenceSource>("time");
  const [referenceDate, setReferenceDate] = useState("");
  const [referenceTime, setReferenceTime] = useState("");
  const [otherId, setOtherId] = useState("");
  const [metadataById, setMetadataById] = useState<Record<string, StoredFileMetadata>>({});
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [preview, setPreview] = useState<{ key: string; data: FileBulkCaptureDatePreview } | null>(null);
  const cancelRef = useRef(false);

  const count = fileIds.length;
  const tooMany = count > MAX_CAPTURE_DATE_SELECTION;
  const selectedReferenceItems = useMemo(() => {
    const selected = new Set(fileIds);
    return referenceItems.filter((item) => selected.has(item.id));
  }, [referenceItems, fileIds]);

  // Metadaten des Referenzfotos (aktuelle Kamerazeit) bzw. des Fotos der anderen Kamera
  useEffect(() => {
    for (const id of [referenceId, otherId]) {
      if (!id || metadataById[id]) continue;
      browserApiFetch<StoredFileMetadata>(`/api/stored-files/${id}/metadata`)
        .then((metadata) => {
          if (metadata) setMetadataById((current) => ({ ...current, [id]: metadata }));
        })
        .catch(() => {});
    }
  }, [referenceId, otherId, metadataById]);

  // Vorzeichenbehafteter Versatz in Sekunden (null = unvollständig/ungültig)
  let shiftSeconds: number | null = null;
  let referenceProblem: string | null = null;
  if (mode === "shift" && shiftKind === "offset") {
    const values = [parseAmount(days), parseAmount(hours), parseAmount(minutes)];
    if (values.every((value) => value !== null)) {
      const [d, h, m] = values as number[];
      shiftSeconds = (direction === "earlier" ? -1 : 1) * totalSeconds(d, h, m);
    }
  } else if (mode === "shift") {
    const current = referenceId && metadataById[referenceId] ? cameraSeconds(metadataById[referenceId]) : null;
    if (referenceId && metadataById[referenceId] && current === null) referenceProblem = t("referenceNoTime");
    const target = referenceSource === "time"
      ? inputSeconds(referenceDate, referenceTime)
      : otherId && metadataById[otherId] ? cameraSeconds(metadataById[otherId]) : null;
    if (referenceSource === "photo" && otherId && metadataById[otherId] && target === null) referenceProblem = t("referenceNoTime");
    if (current !== null && target !== null) shiftSeconds = target - current;
  }
  const split = shiftSeconds !== null ? splitOffset(shiftSeconds) : null;
  const shiftValid = split !== null && shiftSeconds !== 0;
  const noTimeNote = split ? noTimeShiftNote(split.days, split.hours, t, split.minutes, split.seconds) : null;
  const valid = !tooMany && count > 0 && (mode === "set" ? Boolean(date) : mode === "shift" ? shiftValid : true);

  function buildRequest(): CaptureCorrectionRequest {
    if (mode === "set") return { mode, date, time };
    if (mode === "shift" && split) return { mode, ...split };
    return { mode: "reset" };
  }

  const payloadKey = valid ? JSON.stringify(captureCorrectionPayload(buildRequest())) : "";
  const currentPreview = preview && preview.key === payloadKey ? preview.data : null;

  async function loadPreview() {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const body = captureCorrectionPayload(buildRequest());
      const outcome = await runInChunks(fileIds, MAX_CAPTURE_DATE_BULK, (ids) =>
        browserApiFetch<FileBulkCaptureDatePreview>("/api/files/bulk-capture-date/preview", { method: "POST", body: JSON.stringify({ file_ids: ids, ...body }) }),
      );
      const merged = mergePreview(outcome.results.filter((result): result is FileBulkCaptureDatePreview => Boolean(result)));
      if (merged) setPreview({ key: payloadKey, data: merged });
      if (outcome.failedChunks > 0) showToast(t("previewError"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function undo(batchId: string) {
    try {
      const result = await browserApiFetch<CaptureChangeUndoResult>(`/api/capture-changes/${batchId}/undo`, { method: "POST" });
      const restored = result?.restored_ids.length ?? 0;
      showToast(t("undoDone", { count: restored }), "success");
      if (result?.conflict_ids.length) showToast(t("undoConflicts", { count: result.conflict_ids.length }), "info");
      onDone();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("undoError"), "error");
    }
  }

  async function apply() {
    if (!valid || busy) return;
    const request = buildRequest();
    if (!(await confirmCorrection(request, count))) return;
    setBusy(true);
    cancelRef.current = false;
    let batchId: string | null = null;
    try {
      const body = captureCorrectionPayload(request);
      const outcome = await runInChunks(
        fileIds,
        MAX_CAPTURE_DATE_BULK,
        async (ids) => {
          const result = await browserApiFetch<FileBulkCaptureDateResult>("/api/files/bulk-capture-date", {
            method: "POST",
            body: JSON.stringify({
              file_ids: ids,
              ...body,
              ...(batchId ? { batch_id: batchId } : {}),
              ...(uploadJobId ? { upload_job_id: uploadJobId } : {}),
            }),
          });
          batchId = batchId ?? result?.batch_id ?? null;
          return result;
        },
        {
          onProgress: (value) => setProgress(count > MAX_CAPTURE_DATE_BULK ? value : null),
          shouldCancel: () => cancelRef.current,
        },
      );
      const results = outcome.results.filter((result): result is FileBulkCaptureDateResult => Boolean(result));
      if (outcome.failedChunks > 0 && results.length === 0) {
        const error = outcome.firstError;
        showToast(error instanceof Error && error.message ? error.message : t("error"), "error");
        return;
      }
      const total = (key: keyof FileBulkCaptureDateResult) => results.reduce((sum, result) => sum + ((result[key] as string[] | undefined)?.length ?? 0), 0);
      const updated = total("updated_ids");
      const notes = [
        total("unchanged_ids") ? t("resultUnchanged", { count: total("unchanged_ids") }) : null,
        total("skipped_no_date_ids") ? t("resultSkipped", { count: total("skipped_no_date_ids") }) : null,
        total("no_time_unchanged_ids") ? t("resultNoTimeUnchanged", { count: total("no_time_unchanged_ids") }) : null,
        total("date_only_ids") ? t("resultDateOnly", { count: total("date_only_ids") }) : null,
        total("invalid_ids") ? t("resultInvalid", { count: total("invalid_ids") }) : null,
        total("not_found_ids") ? t("resultNotFound", { count: total("not_found_ids") }) : null,
        total("skipped_not_image_ids") ? t("resultNotImage", { count: total("skipped_not_image_ids") }) : null,
        outcome.failedChunks ? t("resultChunksFailed", { count: outcome.failedChunks }) : null,
        outcome.cancelled ? t("resultCancelled") : null,
      ].filter((note): note is string => Boolean(note));
      const undoBatch = batchId;
      if (updated > 0) {
        if (undoBatch) showToast(t("resultUpdated", { count: updated }), "success", { action: { label: t("undoAction"), onClick: () => void undo(undoBatch) } });
        else showToast(t("resultUpdated", { count: updated }), "success");
      }
      if (notes.length > 0) showToast(notes.join(" "), updated > 0 ? "info" : "error");
      onDone();
      onClose();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("error"), "error");
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={t("dialogTitle")} onClose={onClose} className="capture-date-dialog" size="wide">
      <div className="grid capture-date-dialog-body">
        <p className="muted">{t("selectionCount", { count })}</p>
        {tooMany ? <StatusBanner tone="error" message={t("tooMany", { max: MAX_CAPTURE_DATE_SELECTION })} /> : null}
        <FilterTabs<CaptureCorrectionMode>
          options={[
            { value: "set", label: t("modeSet") },
            { value: "shift", label: t("modeShift") },
            { value: "reset", label: t("modeReset") },
          ]}
          value={mode}
          onChange={setMode}
        />
        {mode === "set" ? (
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("dateLabel")}</span>
              <DateInput value={date} onChange={setDate} max={todayIso()} aria-label={t("dateLabel")} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("timeLabel")}</span>
              <TimeInput value={time} onChange={setTime} aria-label={t("timeLabel")} />
              <span className="field-help">{t("timeHelp")}</span>
            </label>
          </div>
        ) : null}
        {mode === "shift" ? (
          <>
            <FilterTabs<ShiftKind>
              variant="chips"
              options={[
                { value: "offset", label: t("shiftByOffset") },
                { value: "reference", label: t("shiftByReference"), disabled: selectedReferenceItems.length === 0 },
              ]}
              value={shiftKind}
              onChange={setShiftKind}
            />
            {shiftKind === "offset" ? (
              <>
                <FilterTabs<"earlier" | "later">
                  options={[
                    { value: "earlier", label: t("directionEarlier") },
                    { value: "later", label: t("directionLater") },
                  ]}
                  value={direction}
                  onChange={setDirection}
                />
                <div className="capture-date-offset-fields">
                  <label className="field-stack">
                    <span className="field-label">{t("shiftDaysLabel")}</span>
                    <input type="number" min={0} step={1} inputMode="numeric" value={days} onChange={(event) => setDays(event.target.value)} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("shiftHoursLabel")}</span>
                    <input type="number" min={0} step={1} inputMode="numeric" value={hours} onChange={(event) => setHours(event.target.value)} />
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("shiftMinutesLabel")}</span>
                    <input type="number" min={0} step={1} inputMode="numeric" value={minutes} onChange={(event) => setMinutes(event.target.value)} />
                  </label>
                </div>
                <p className="field-help">{t("shiftHelp")}</p>
              </>
            ) : (
              <>
                <label className="field-stack">
                  <span className="field-label">{t("referencePhotoLabel")}</span>
                  <SearchableSelect
                    options={selectedReferenceItems}
                    getId={(item) => item.id}
                    getLabel={(item) => item.original_name}
                    value={referenceId || null}
                    onChange={(item) => setReferenceId(item?.id ?? "")}
                    placeholder={t("referencePhotoPlaceholder")}
                  />
                  {referenceId && metadataById[referenceId] ? (
                    <span className="field-help">
                      {t("referenceCurrent", {
                        value: formatMoment(
                          metadataById[referenceId].capture_corrected_at ?? metadataById[referenceId].exif_taken_at ?? null,
                          Boolean(cameraSeconds(metadataById[referenceId]) !== null),
                        ),
                      })}
                    </span>
                  ) : null}
                </label>
                <FilterTabs<ReferenceSource>
                  variant="chips"
                  options={[
                    { value: "time", label: t("referenceSourceTime") },
                    { value: "photo", label: t("referenceSourcePhoto"), disabled: referenceItems.length < 2 },
                  ]}
                  value={referenceSource}
                  onChange={setReferenceSource}
                />
                {referenceSource === "time" ? (
                  <div className="two-col">
                    <label className="field-stack">
                      <span className="field-label">{t("referenceDateLabel")}</span>
                      <DateInput value={referenceDate} onChange={setReferenceDate} max={todayIso()} aria-label={t("referenceDateLabel")} />
                    </label>
                    <label className="field-stack">
                      <span className="field-label">{t("referenceTimeLabel")}</span>
                      <TimeInput value={referenceTime} onChange={setReferenceTime} aria-label={t("referenceTimeLabel")} />
                    </label>
                  </div>
                ) : (
                  <label className="field-stack">
                    <span className="field-label">{t("referenceOtherLabel")}</span>
                    <SearchableSelect
                      options={referenceItems.filter((item) => item.id !== referenceId)}
                      getId={(item) => item.id}
                      getLabel={(item) => item.original_name}
                      value={otherId || null}
                      onChange={(item) => setOtherId(item?.id ?? "")}
                      placeholder={t("referencePhotoPlaceholder")}
                    />
                    <span className="field-help">{t("referenceOtherHelp")}</span>
                  </label>
                )}
                {referenceProblem ? <StatusBanner tone="warning" message={referenceProblem} /> : null}
                {shiftValid && split ? (
                  <p className="capture-date-reference-result">
                    {t("referenceResult", describeOffset(split.days, split.hours, t, split.minutes, split.seconds))}
                  </p>
                ) : null}
              </>
            )}
            {shiftValid && noTimeNote ? <StatusBanner tone="neutral" message={noTimeNote} /> : null}
            <p className="field-help">{t("timezoneNote")}</p>
          </>
        ) : null}
        {mode === "reset" ? <p className="field-help">{t("resetHelp")}</p> : null}
        {currentPreview ? <CapturePreview preview={currentPreview} /> : null}
        {progress ? (
          <div className="photo-bulk-progress" role="status" aria-live="polite">
            <span>{t("applyProgress", { done: progress.done, total: progress.total })}</span>
            <button type="button" className="button-secondary button-ghost" onClick={() => { cancelRef.current = true; }}>{t("cancel")}</button>
          </div>
        ) : null}
        <StatusBanner tone="neutral" message={t("hint")} />
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose} disabled={busy}>{t("cancel")}</button>
        <button type="button" className="button-secondary" onClick={() => void loadPreview()} disabled={!valid || busy}>{t("previewAction")}</button>
        <button type="button" className="button-primary" onClick={() => void apply()} disabled={!valid || busy}>{t("apply")}</button>
      </div>
    </Modal>
  );
}

function CapturePreview({ preview }: { preview: FileBulkCaptureDatePreview }) {
  const t = useTranslations("photos.captureCorrection");
  const lines = [
    t("previewWillChange", { count: preview.will_change }),
    preview.unchanged ? t("resultUnchanged", { count: preview.unchanged }) : null,
    preview.no_date ? t("previewNoDate", { count: preview.no_date }) : null,
    preview.date_only_unchanged ? t("resultNoTimeUnchanged", { count: preview.date_only_unchanged }) : null,
    preview.date_only_changed ? t("resultDateOnly", { count: preview.date_only_changed }) : null,
    preview.invalid ? t("resultInvalid", { count: preview.invalid }) : null,
    preview.not_found ? t("resultNotFound", { count: preview.not_found }) : null,
    preview.not_image ? t("resultNotImage", { count: preview.not_image }) : null,
    preview.day_changes ? t("previewDayChanges", { count: preview.day_changes }) : null,
    preview.event_changes ? t("previewEventChanges", { count: preview.event_changes }) : null,
  ].filter((line): line is string => Boolean(line));
  const eventLabel = (event: { title: string; date: string } | null) => (event ? `${event.title} (${formatDate(event.date)})` : t("previewNoEvent"));
  return (
    <section className="capture-preview" aria-label={t("previewTitle")}>
      <h3 className="capture-preview-title">{t("previewTitle")}</h3>
      <ul className="capture-preview-counts">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {preview.event_transitions.length > 0 ? (
        <ul className="capture-preview-counts">
          {preview.event_transitions.map((transition, index) => (
            <li key={index}>
              {t("previewTransition", { count: transition.count, from: eventLabel(transition.from_event), to: eventLabel(transition.to_event) })}
            </li>
          ))}
        </ul>
      ) : null}
      {preview.samples.length > 0 ? (
        <ul className="capture-preview-samples">
          {preview.samples.map((sample) => (
            <li key={sample.id} className="capture-preview-sample">
              {/* eslint-disable-next-line @next/next/no-img-element -- Vorschaubild aus dem Backend, wie im Papierkorb */}
              <img src={`${browserApiBaseUrl}${sample.thumbnail_url}`} alt="" loading="lazy" />
              <span className="capture-preview-name">{sample.name}</span>
              <span className="capture-preview-change">
                {t("previewBeforeAfter", { before: formatMoment(sample.before, sample.before_has_time), after: formatMoment(sample.after, sample.after_has_time) })}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
