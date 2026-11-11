"use client";

import { useTranslations } from "next-intl";

import type { PdfCoverageEntry } from "@/components/protocol/use-pdf-coverage";

/** Dezenter Hinweis im Editor: dieser Punkt bzw. Baustein hat Inhalt, der nicht im PDF erscheint.
 * Der Grund steht im Tooltip und für Screenreader im Text. */
export function PdfOmittedHint({ entry }: { entry: PdfCoverageEntry | undefined }) {
  const t = useTranslations("protocols.pdfCoverage");
  if (!entry) return null;
  const reason = t(`reason.${entry.reason}`, { count: entry.count ?? 1 });
  return (
    <span className="pdf-omitted-hint" title={reason}>
      {t("notInPdf")}
      <span className="pdf-omitted-hint-reason">: {reason}</span>
    </span>
  );
}
