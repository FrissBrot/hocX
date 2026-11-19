"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { TimeInput } from "@/components/ui/time-input";
import { todayIso } from "@/components/mobile/mobile-utils";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { FileBulkCaptureDateResult } from "@/types/api";

// Korrigiertes Aufnahmedatum (Backend: capture_date.py, Migration 0200). Hat Vorrang vor EXIF und
// Schätzung; das EXIF-Datum und die Datei selbst bleiben unverändert und die Korrektur lässt sich
// wieder entfernen. Jede Änderung braucht eine Bestätigung mit Hinweis, was das bedeutet.

// Obergrenze wie im Backend (MAX_CAPTURE_DATE_BULK in schemas/files.py).
export const MAX_CAPTURE_DATE_BULK = 500;

export type CaptureCorrectionMode = "set" | "shift" | "reset";

export type CaptureCorrectionRequest =
  | { mode: "set"; date: string; time: string }
  | { mode: "shift"; days: number; hours: number }
  | { mode: "reset" };

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

/** Versatz als Text («1 Tag und 2 Stunden») mit Richtung; Tage/Stunden mit gemischten
 * Vorzeichen werden zuerst zu einer Gesamtdauer verrechnet. */
export function describeOffset(days: number, hours: number, t: TFunc): { offset: string; direction: "earlier" | "later" } {
  const total = days * 24 + hours;
  const absolute = Math.abs(total);
  const wholeDays = Math.floor(absolute / 24);
  const restHours = absolute % 24;
  return {
    offset: t("offset", { days: wholeDays, hours: restHours, both: wholeDays > 0 && restHours > 0 ? "yes" : "no" }),
    direction: total < 0 ? "earlier" : "later",
  };
}

export function captureCorrectionPayload(request: CaptureCorrectionRequest) {
  if (request.mode === "set") return { mode: "set", corrected_date: request.date, corrected_time: request.time || null };
  if (request.mode === "shift") return { mode: "shift", shift_days: request.days, shift_hours: request.hours };
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
      message = t("confirmShift", { count, ...describeOffset(request.days, request.hours, t) });
    } else {
      message = t("confirmReset", { count });
    }
    return confirm({ title: t("confirmTitle"), message, confirmLabel: t("confirmLabel") });
  };
}

function parseWholeNumber(value: string): number | null {
  if (value.trim() === "" || value.trim() === "-") return 0;
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : null;
}

/** Mehrfachauswahl der Galerie: «Aufnahmedatum ändern» für alle gewählten Bilder. */
export function PhotoCaptureDateDialog({
  open,
  fileIds,
  onClose,
  onDone,
}: {
  open: boolean;
  fileIds: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useTranslations("photos.captureCorrection");
  const showToast = useToast();
  const confirmCorrection = useCaptureCorrectionConfirm();
  const [mode, setMode] = useState<CaptureCorrectionMode>("set");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [days, setDays] = useState("0");
  const [hours, setHours] = useState("0");
  const [busy, setBusy] = useState(false);

  const count = fileIds.length;
  const tooMany = count > MAX_CAPTURE_DATE_BULK;
  const shiftDays = parseWholeNumber(days);
  const shiftHours = parseWholeNumber(hours);
  const shiftValid = shiftDays !== null && shiftHours !== null && (shiftDays !== 0 || shiftHours !== 0);
  const valid = !tooMany && count > 0 && (mode === "set" ? Boolean(date) : mode === "shift" ? shiftValid : true);

  function buildRequest(): CaptureCorrectionRequest {
    if (mode === "set") return { mode, date, time };
    if (mode === "shift") return { mode, days: shiftDays ?? 0, hours: shiftHours ?? 0 };
    return { mode: "reset" };
  }

  async function apply() {
    if (!valid || busy) return;
    const request = buildRequest();
    if (!(await confirmCorrection(request, count))) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<FileBulkCaptureDateResult>("/api/files/bulk-capture-date", {
        method: "POST",
        body: JSON.stringify({ file_ids: fileIds, ...captureCorrectionPayload(request) }),
      });
      const updated = result?.updated_ids.length ?? 0;
      const notes = [
        result?.unchanged_ids.length ? t("resultUnchanged", { count: result.unchanged_ids.length }) : null,
        result?.skipped_no_date_ids.length ? t("resultSkipped", { count: result.skipped_no_date_ids.length }) : null,
        result?.invalid_ids.length ? t("resultInvalid", { count: result.invalid_ids.length }) : null,
        result?.not_found_ids.length ? t("resultNotFound", { count: result.not_found_ids.length }) : null,
      ].filter((note): note is string => Boolean(note));
      if (updated > 0) showToast(t("resultUpdated", { count: updated }), "success");
      if (notes.length > 0) showToast(notes.join(" "), updated > 0 ? "info" : "error");
      onDone();
      onClose();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("error"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={t("dialogTitle")} onClose={onClose}>
      <div className="grid">
        <p className="muted">{t("selectionCount", { count })}</p>
        {tooMany ? <StatusBanner tone="error" message={t("tooMany", { max: MAX_CAPTURE_DATE_BULK })} /> : null}
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
            <div className="two-col">
              <label className="field-stack">
                <span className="field-label">{t("shiftDaysLabel")}</span>
                <input type="number" step={1} value={days} onChange={(event) => setDays(event.target.value)} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("shiftHoursLabel")}</span>
                <input type="number" step={1} value={hours} onChange={(event) => setHours(event.target.value)} />
              </label>
            </div>
            <p className="field-help">{t("shiftHelp")}</p>
          </>
        ) : null}
        {mode === "reset" ? <p className="field-help">{t("resetHelp")}</p> : null}
        <StatusBanner tone="neutral" message={t("hint")} />
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose} disabled={busy}>{t("cancel")}</button>
        <button type="button" className="button-primary" onClick={() => void apply()} disabled={!valid || busy}>{t("apply")}</button>
      </div>
    </Modal>
  );
}
