"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatSearchHit, PlaceSearchHit } from "@/lib/photos/places";
import { runInChunks } from "@/lib/uploads/upload-jobs";
import type { PlaceAssignResult, PlaceChangeUndoResult } from "@/types/api";

// Ort von Hand setzen (Backend: POST /api/photo-places/assign, Migration 0260). Nur für Fotos ohne
// GPS - Fotos mit echtem GPS behalten ihren Ort und werden gemeldet. Grosse Auswahlen in Stücken zu
// 500 mit derselben Änderung (batch_id), damit «Rückgängig» alles zusammen zurücknimmt.
export const MAX_PLACE_BULK = 500;

type Props = {
  open: boolean;
  fileIds: string[];
  uploadJobId?: string;
  /** «Ort entfernen» anbieten (Einzelfoto mit manuellem Ort, Mehrfachauswahl). */
  allowClear?: boolean;
  onClose: () => void;
  onDone: () => void;
};

export async function undoPlaceChange(batchId: string): Promise<PlaceChangeUndoResult | undefined> {
  return browserApiFetch<PlaceChangeUndoResult>(`/api/place-changes/${batchId}/undo`, { method: "POST" });
}

export function PhotoPlaceDialog({ open, fileIds, uploadJobId, allowClear = true, onClose, onDone }: Props) {
  const t = useTranslations("photos.places");
  const locale = useLocale();
  const showToast = useToast();
  const [selected, setSelected] = useState<PlaceSearchHit | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadOptions(query: string, signal: AbortSignal): Promise<PlaceSearchHit[]> {
    if (query.trim().length < 3) return [];
    return (await browserApiFetch<PlaceSearchHit[]>(`/api/places/search?q=${encodeURIComponent(query.trim())}&limit=10`, { signal })) ?? [];
  }

  async function undo(batchId: string) {
    try {
      const result = await undoPlaceChange(batchId);
      showToast(t("undoDone", { count: result?.restored_ids.length ?? 0 }), "success");
      if (result?.conflict_ids.length) showToast(t("undoConflicts", { count: result.conflict_ids.length }), "info");
      onDone();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("undoError"), "error");
    }
  }

  async function apply(placeKey: string | null) {
    if (busy) return;
    setBusy(true);
    let batchId: string | null = null;
    try {
      const outcome = await runInChunks(fileIds, MAX_PLACE_BULK, async (ids) => {
        const result = await browserApiFetch<PlaceAssignResult>("/api/photo-places/assign", {
          method: "POST",
          body: JSON.stringify({ file_ids: ids, place_key: placeKey, upload_job_id: uploadJobId ?? null, batch_id: batchId }),
        });
        batchId = batchId ?? result?.batch_id ?? null;
        return result;
      });
      const updated = outcome.results.reduce((sum, result) => sum + (result?.updated_ids.length ?? 0), 0);
      const skipped = outcome.results.reduce((sum, result) => sum + (result?.skipped_gps_ids.length ?? 0), 0);
      if (outcome.results.length === 0 && outcome.failedChunks > 0) {
        const error = outcome.firstError;
        showToast(error instanceof Error && error.message ? error.message : t("saveError"), "error");
        return;
      }
      const undoBatch: string | null = batchId;
      const message = placeKey ? t("setDone", { count: updated }) : t("clearDone", { count: updated });
      showToast(message, "success", undoBatch && updated > 0 ? { action: { label: t("undoAction"), onClick: () => void undo(undoBatch) } } : undefined);
      if (skipped > 0) showToast(t("skippedGps", { count: skipped }), "info");
      if (outcome.failedChunks > 0) showToast(t("partialError", { count: outcome.failedChunks }), "error");
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} title={t("dialogTitle", { count: fileIds.length })} onClose={onClose}>
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">{t("placeField")}</span>
          <SearchableSelect<PlaceSearchHit, string>
            options={[]}
            loadOptions={loadOptions}
            selectedOption={selected}
            getId={(hit) => hit.key}
            getLabel={(hit) => formatSearchHit(hit, t, locale)}
            value={selected?.key ?? null}
            onChange={(hit) => setSelected(hit)}
            placeholder={t("placePlaceholder")}
            searchPlaceholder={t("searchPlaceholder")}
            emptyLabel={t("searchEmpty")}
            disabled={busy}
          />
          <span className="field-help">{t("gpsHint")}</span>
        </label>
        <p className="field-help">{t("attribution")}</p>
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose} disabled={busy}>{t("cancel")}</button>
        {allowClear ? (
          <button type="button" className="button-secondary" onClick={() => void apply(null)} disabled={busy}>{t("clear")}</button>
        ) : null}
        <button type="button" className="button-primary" onClick={() => void apply(selected?.key ?? null)} disabled={busy || !selected}>
          {t("apply")}
        </button>
      </div>
    </Modal>
  );
}
