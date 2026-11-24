"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { undoPlaceChange } from "@/components/photos/photo-place-dialog";
import { DataTable } from "@/components/ui/data-table";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import type { PlaceChangeBatch } from "@/types/api";

/** Ortsänderungen eines Upload-Vorgangs (Reiter «Korrekturen») mit Rückgängig - wie die
 * Datumskorrekturen darüber. Leer: nichts anzeigen. */
export function UploadPlaceChanges({ jobId, onUndone }: { jobId: string; onUndone: () => void }) {
  const t = useTranslations("photos.places");
  const tUploads = useTranslations("uploads");
  const locale = useLocale();
  const showToast = useToast();
  const [batches, setBatches] = useState<PlaceChangeBatch[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    browserApiFetch<PlaceChangeBatch[]>(`/api/place-changes?upload_job_id=${jobId}`)
      .then((data) => setBatches(Array.isArray(data) ? data : []))
      .catch(() => setBatches([]));
  }

  useEffect(load, [jobId]);

  async function undo(batch: PlaceChangeBatch) {
    setBusy(batch.id);
    try {
      const result = await undoPlaceChange(batch.id);
      showToast(t("undoDone", { count: result?.restored_ids.length ?? 0 }), "success");
      if (result?.conflict_ids.length) showToast(t("undoConflicts", { count: result.conflict_ids.length }), "info");
      load();
      onUndone();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("undoError"), "error");
    } finally {
      setBusy(null);
    }
  }

  if (batches.length === 0) return null;
  return (
    <section aria-label={t("changesTitle")}>
      <h2 className="section-title">{t("changesTitle")}</h2>
      <DataTable columns={[tUploads("corrections.when"), tUploads("corrections.what"), tUploads("corrections.who"), tUploads("corrections.count"), tUploads("corrections.action")]}>
        {batches.map((batch) => (
          <tr key={batch.id}>
            <td>{formatDateTime(batch.created_at, locale)}</td>
            <td>{batch.mode === "set" ? t("changeSet", { place: batch.params.place_name ?? batch.params.place_key ?? "" }) : t("changeClear")}</td>
            <td>{batch.created_by_name ?? "–"}</td>
            <td>{tUploads("corrections.countValue", { count: batch.updated_count, remaining: batch.remaining })}</td>
            <td>
              {batch.undone_at ? (
                <span className="muted">{tUploads("corrections.undoneAt", { date: formatDateTime(batch.undone_at, locale) })}</span>
              ) : batch.can_undo ? (
                <button type="button" className="button-secondary" disabled={busy !== null} onClick={() => void undo(batch)}>{tUploads("corrections.undo")}</button>
              ) : (
                <span className="muted">{tUploads("corrections.noFiles")}</span>
              )}
            </td>
          </tr>
        ))}
      </DataTable>
    </section>
  );
}
