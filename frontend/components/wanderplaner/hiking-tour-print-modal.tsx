"use client";

import { useLocale, useTranslations } from "next-intl";
import { FormEvent, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { toIntlLocale } from "@/lib/utils/format";
import { HikingTourPrintResult } from "@/types/api";

// Auftrag Abschnitt 15 - dieselben Werte wie PAPER_SIZES_MM/DEFAULT_SCALES im Backend
// (app/core/print_layout.py); Architektur ist dort fuer weitere Massstaebe offen, hier nur
// die drei geforderten Presets.
const PRINT_PAPER_OPTIONS = ["A4", "A3", "A2", "A1"] as const;
const PRINT_SCALE_OPTIONS = [10_000, 25_000, 50_000] as const;

/** Druckdialog (PDF-Kartenblätter), gemeinsam für Desktop und Mobile; auf dem Handy als Sheet. */
export function HikingTourPrintModal({ tourId, open, onClose, sheet = false }: { tourId: string; open: boolean; onClose: () => void; sheet?: boolean }) {
  const t = useTranslations("wanderplaner");
  const intlLocale = toIntlLocale(useLocale());
  const showToast = useToast();
  const [printForm, setPrintForm] = useState({ paper: "A4", orientation: "landscape", scale: 25_000 });
  const [printing, setPrinting] = useState(false);
  const [printResult, setPrintResult] = useState<HikingTourPrintResult | null>(null);

  function close() {
    setPrintResult(null);
    onClose();
  }

  async function handlePrint(event: FormEvent) {
    event.preventDefault();
    setPrinting(true);
    setPrintResult(null);
    try {
      const result = await browserApiFetch<HikingTourPrintResult>(`/api/hiking-tours/${tourId}/print`, {
        method: "POST",
        body: JSON.stringify({
          paper: printForm.paper,
          orientation: printForm.orientation,
          scale: printForm.scale,
        }),
        // browserApiFetch's Standard-Timeout (15s) reicht nicht: WMTS-Kachelabruf + pdflatex-
        // Kompilierung dauern je nach Blattanzahl/Massstab real 20-60+ Sekunden (siehe
        // hiking_tour_print_service.py - der Backend-seitige pdflatex-Timeout selbst ist schon
        // 120s). Ohne diese Ueberschreibung brach der Request client-seitig ab, waehrend der
        // Server noch am Rechnen war (gefunden per echtem E2E-Test gegen den echten
        // swisstopo-Dienst, nicht nur durch gemockte Unit-Tests).
        signal: AbortSignal.timeout(180_000),
      });
      setPrintResult(result);
      showToast(t("detail.toast.printCreated"), "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("detail.toast.printError"), "error");
    } finally {
      setPrinting(false);
    }
  }

  return (
    <Modal open={open} title={t("detail.print")} onClose={close} {...(sheet ? { size: "sheet" as const, className: "mobile-sheet" } : {})}>
      <form onSubmit={(event) => void handlePrint(event)}>
        <div className="grid two-col">
          <label className="field-stack">
            <span className="field-label">{t("detail.printModal.paper")}</span>
            <Select value={printForm.paper} onChange={(event) => setPrintForm((prev) => ({ ...prev, paper: event.target.value }))}>
              {PRINT_PAPER_OPTIONS.map((paper) => (
                <option key={paper} value={paper}>
                  {paper}
                </option>
              ))}
            </Select>
          </label>
          <label className="field-stack">
            <span className="field-label">{t("detail.printModal.orientation")}</span>
            <Select
              value={printForm.orientation}
              onChange={(event) => setPrintForm((prev) => ({ ...prev, orientation: event.target.value }))}
            >
              <option value="portrait">{t("detail.printModal.portrait")}</option>
              <option value="landscape">{t("detail.printModal.landscape")}</option>
            </Select>
          </label>
          <label className="field-stack">
            <span className="field-label">{t("detail.printModal.scale")}</span>
            <Select
              value={printForm.scale}
              onChange={(event) => setPrintForm((prev) => ({ ...prev, scale: Number(event.target.value) }))}
            >
              {PRINT_SCALE_OPTIONS.map((scale) => (
                <option key={scale} value={scale}>
                  {t("detail.printModal.scaleOption", { scale: scale.toLocaleString(intlLocale) })}
                </option>
              ))}
            </Select>
          </label>
        </div>
        {printResult && (
          <p className="field-help">
            {t.rich("detail.printModal.result", {
              count: printResult.sheet_count,
              link: (chunks) => (
                <a href={printResult.content_url} target="_blank" rel="noreferrer">
                  {chunks}
                </a>
              ),
            })}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={close}>
            {t("actions.close")}
          </button>
          <button type="submit" className="button-primary" disabled={printing}>
            {printing ? t("detail.printModal.creating") : t("detail.printModal.submit")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
