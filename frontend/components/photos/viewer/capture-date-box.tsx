"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { todayIso } from "@/components/mobile/mobile-utils";
import { DateInput } from "@/components/ui/date-input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { TimeInput } from "@/components/ui/time-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatCaptureDateTime, formatDate } from "@/lib/utils/format";
import type { FileBulkCaptureDateResult, StoredFileMetadata } from "@/types/api";
import { CaptureMoment, captureDateKind, parseWholeNumber, shiftBase, shiftPreview } from "./viewer-logic";

type Mode = "set" | "shift" | "reset";

function formatMoment(moment: CaptureMoment | null): string {
  if (!moment) return "—";
  return moment.time ? `${formatDate(moment.date)}, ${moment.time}` : formatDate(moment.date);
}

/** Aufnahmedatum der Foto-Ansicht: Herkunft (EXIF, geschätzt, korrigiert, unbekannt) und «Ändern»
 * mit Setzen (Datum + optionale Uhrzeit), Verschieben (Tage/Stunden mit Vorschau) und Zurücksetzen.
 * Jede Änderung braucht eine zweite Bestätigung mit Hinweis auf Neueinsortierung und
 * Termin-Zuordnung. Gespeichert wird als Korrektur (capture_date.py, Migration 0200): das
 * ursprüngliche Datum bleibt erhalten und lässt sich wiederherstellen. */
export function CaptureDateBox({
  fileId,
  metadataUrl,
  metadata,
  onSaved,
}: {
  fileId: string;
  metadataUrl: string;
  metadata: StoredFileMetadata | null;
  onSaved: (metadata: StoredFileMetadata) => void;
}) {
  const t = useTranslations("photos.viewer.dateBox");
  const tc = useTranslations("photos.captureCorrection");
  const locale = useLocale();
  const [editing, setEditing] = useState(false);
  if (!metadata) return <div className="photo-date-box" aria-busy="true">…</div>;

  const kind = captureDateKind(metadata);
  const canEdit = Boolean(metadata.can_edit_capture_date);
  const corrected = metadata.capture_corrected_at;
  let value: string;
  if (kind === "corrected" && corrected) {
    value = metadata.capture_corrected_has_time ? formatCaptureDateTime(corrected, null, locale) : formatDate(corrected.slice(0, 10));
  } else if (kind === "exif") value = formatCaptureDateTime(metadata.exif_taken_at, metadata.exif_taken_offset, locale);
  else if (kind === "estimated") value = formatDate(metadata.estimated_taken_on);
  else value = t("unknownValue");

  let note: string;
  if (kind === "corrected") {
    if (metadata.exif_taken_at) note = tc("originalExif", { value: formatCaptureDateTime(metadata.exif_taken_at, metadata.exif_taken_offset, locale) });
    else if (metadata.estimated_taken_on) note = tc("originalEstimated", { value: formatDate(metadata.estimated_taken_on) });
    else note = tc("originalNone");
  } else note = t(`${kind}Note`);
  // Stand der Bilddatei (Migration 0203) - nur ein Hinweis, das angezeigte Datum gilt sofort.
  const fileState = metadata.capture_file_state;
  let fileStateNote: string | null = null;
  if (fileState === "pending") fileStateNote = tc("fileStatePending");
  else if (corrected && fileState === "written") fileStateNote = tc("fileStateWritten");
  else if (corrected && fileState === "unsupported") fileStateNote = tc("fileStateUnsupported");
  else if (corrected && fileState === "failed") fileStateNote = tc("fileStateFailed");

  return (
    <div className={`photo-date-box photo-date-box-${kind}`}>
      <div className="photo-date-box-head">
        <span className="photo-date-box-kicker">{t(`${kind}Kicker`)}</span>
        {canEdit && !editing ? (
          <button type="button" className="photo-date-box-action" onClick={() => setEditing(true)}>{t("change")}</button>
        ) : null}
      </div>
      {editing ? (
        <CaptureDateEditor
          fileId={fileId}
          metadataUrl={metadataUrl}
          metadata={metadata}
          onDone={(saved) => {
            setEditing(false);
            if (saved) onSaved(saved);
          }}
        />
      ) : (
        <strong className="photo-date-box-value">{value}</strong>
      )}
      <span className="photo-date-box-note">{note}</span>
      {fileStateNote ? <span className="photo-date-box-note">{fileStateNote}</span> : null}
    </div>
  );
}

function CaptureDateEditor({
  fileId,
  metadataUrl,
  metadata,
  onDone,
}: {
  fileId: string;
  metadataUrl: string;
  metadata: StoredFileMetadata;
  onDone: (saved: StoredFileMetadata | null) => void;
}) {
  const t = useTranslations("photos.viewer.dateBox");
  const tc = useTranslations("photos.captureCorrection");
  const locale = useLocale();
  const showToast = useToast();
  const base = shiftBase(metadata);
  const current = metadata.capture_corrected_at ?? metadata.exif_taken_at ?? (metadata.estimated_taken_on ? `${metadata.estimated_taken_on}T12:00` : null);
  const currentHasTime = metadata.capture_corrected_at ? Boolean(metadata.capture_corrected_has_time) : Boolean(metadata.exif_taken_at);
  const [mode, setModeState] = useState<Mode>("set");
  const [date, setDateState] = useState(current ? current.slice(0, 10) : "");
  const [time, setTimeState] = useState(current && currentHasTime ? current.slice(11, 16) : "");
  const [days, setDaysState] = useState("0");
  const [hours, setHoursState] = useState("0");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  // Jede Änderung an der Eingabe verlangt eine neue Bestätigung.
  const edit = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value);
    setConfirming(false);
  };
  const setMode = edit(setModeState);
  const setDate = edit(setDateState);
  const setTime = edit(setTimeState);
  const setDays = edit(setDaysState);
  const setHours = edit(setHoursState);

  const shiftDays = parseWholeNumber(days);
  const shiftHours = parseWholeNumber(hours);
  const preview = shiftDays !== null && shiftHours !== null ? shiftPreview(metadata, shiftDays, shiftHours) : null;
  const valid =
    mode === "set" ? Boolean(date)
    : mode === "shift" ? base !== null && shiftDays !== null && shiftHours !== null && (shiftDays !== 0 || shiftHours !== 0)
    : true;

  let question = "";
  if (mode === "set") question = t("confirmSet", { date: formatMoment({ date, time: time || null }) });
  else if (mode === "shift") question = t("confirmShift", { date: formatMoment(preview) });
  else question = t("confirmReset");

  let resetTarget: string;
  if (metadata.exif_taken_at) resetTarget = t("resetTargetExif", { value: formatCaptureDateTime(metadata.exif_taken_at, metadata.exif_taken_offset, locale) });
  else if (metadata.estimated_taken_on) resetTarget = t("resetTargetEstimated", { value: formatDate(metadata.estimated_taken_on) });
  else resetTarget = t("resetTargetNone");

  async function submit() {
    if (!valid || busy) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    try {
      let saved: StoredFileMetadata | null = null;
      if (mode === "shift") {
        const result = await browserApiFetch<FileBulkCaptureDateResult>("/api/files/bulk-capture-date", {
          method: "POST",
          body: JSON.stringify({ file_ids: [fileId], mode: "shift", shift_days: shiftDays ?? 0, shift_hours: shiftHours ?? 0 }),
        });
        if (result?.invalid_ids.length) throw new Error(tc("resultInvalid", { count: 1 }));
        if (result?.skipped_no_date_ids.length) throw new Error(tc("resultSkipped", { count: 1 }));
        if (result?.not_found_ids.length) throw new Error(tc("resultNotFound", { count: 1 }));
        saved = await browserApiFetch<StoredFileMetadata>(metadataUrl);
      } else {
        saved = await browserApiFetch<StoredFileMetadata>(`/api/stored-files/${fileId}/capture-correction`, {
          method: "PATCH",
          body: JSON.stringify(mode === "set" ? { corrected_date: date, corrected_time: time || null } : { corrected_date: null }),
        });
      }
      showToast(t("saved"), "success");
      onDone(saved);
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : tc("error"), "error");
      setBusy(false);
    }
  }

  const modes = [
    { value: "set" as const, label: t("modeSet") },
    { value: "shift" as const, label: t("modeShift"), disabled: base === null },
    ...(metadata.capture_corrected_at ? [{ value: "reset" as const, label: t("modeReset") }] : []),
  ];

  return (
    <div className="photo-viewer-correction">
      <SegmentedControl<Mode> aria-label={t("modeLabel")} value={mode} onChange={setMode} options={modes} />
      {mode === "set" ? (
        <div className="photo-viewer-correction-fields">
          <label className="field-stack">
            <span className="field-label">{tc("dateLabel")}</span>
            <DateInput value={date} onChange={setDate} max={todayIso()} aria-label={tc("dateLabel")} />
          </label>
          <label className="field-stack">
            <span className="field-label">{tc("timeLabel")}</span>
            <TimeInput value={time} onChange={setTime} aria-label={tc("timeLabel")} />
          </label>
        </div>
      ) : null}
      {mode === "shift" ? (
        <>
          <div className="photo-viewer-correction-fields">
            <label className="field-stack">
              <span className="field-label">{tc("shiftDaysLabel")}</span>
              <input type="number" step={1} inputMode="numeric" value={days} onChange={(event) => setDays(event.target.value)} />
            </label>
            <label className="field-stack">
              <span className="field-label">{tc("shiftHoursLabel")}</span>
              <input type="number" step={1} inputMode="numeric" value={hours} onChange={(event) => setHours(event.target.value)} />
            </label>
          </div>
          <p className="field-help" aria-live="polite">
            {t("shiftHelp")} <strong className="photo-viewer-shift-preview">{t("shiftPreview", { value: formatMoment(preview) })}</strong>
          </p>
        </>
      ) : null}
      {mode === "reset" ? <p className="field-help">{t("resetHelp", { target: resetTarget })}</p> : null}
      {confirming ? (
        <div className="photo-viewer-correction-confirm" role="status">
          <strong>{question}</strong> {t("confirmHint")}
        </div>
      ) : null}
      <div className="photo-viewer-correction-actions">
        <button type="button" className="button-ghost" onClick={() => onDone(null)} disabled={busy}>{tc("cancel")}</button>
        <button type="button" className="button-primary" onClick={() => void submit()} disabled={busy || !valid}>
          {confirming ? t("confirmAction") : tc("apply")}
        </button>
      </div>
    </div>
  );
}
