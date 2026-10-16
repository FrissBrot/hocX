"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { countUploadResults } from "@/lib/utils/upload-results";
import { MetadataField, UploadFailureCode, UploadFileResult } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

const STATUS_VARIANT = { uploaded: "success", skipped: "neutral", metadata_updated: "info", failed: "danger" } as const;

/** "24 Bilder verarbeitet: 12 hochgeladen, 8 übersprungen, 4 übersprungen und Metadaten
 * ergänzt" - nur die Fälle, die tatsächlich vorkommen. `t` aus dem "files"-Namespace. */
export function uploadResultsSummary(results: UploadFileResult[], t: TFunc, noun: "images" | "files" = "files"): string {
  const counts = countUploadResults(results);
  const parts = [
    counts.uploaded ? t("uploadResults.partUploaded", { count: counts.uploaded }) : null,
    counts.skipped ? t("uploadResults.partSkipped", { count: counts.skipped }) : null,
    counts.metadataUpdated ? t("uploadResults.partMetadataUpdated", { count: counts.metadataUpdated }) : null,
    counts.failed ? t("uploadResults.partFailed", { count: counts.failed }) : null,
  ].filter(Boolean);
  const values = { count: counts.total, parts: parts.join(", ") };
  return noun === "images" ? t("uploadResults.summaryImages", values) : t("uploadResults.summaryFiles", values);
}

// Codes, für die es eine eigene Übersetzung gibt. Regelverstösse (rule_violation) tragen den
// Regeltext selbst in `message`; unbekannte Codes (neuerer Server) fallen auf `message` zurück.
const TRANSLATED_FAILURES: readonly UploadFailureCode[] = [
  "too_large", "unsupported_format", "scan_failed", "infected", "quota_exceeded", "heic_unreadable",
];

/** Übersetzter Grund eines Fehlschlags (IMGMETA-012) statt des deutschen Servertexts. */
export function uploadFailureText(result: UploadFileResult, t: TFunc): string | null {
  if (result.code && TRANSLATED_FAILURES.includes(result.code)) return t(`uploadResults.errors.${result.code}`, result.params ?? {});
  return result.message ?? null;
}

function appliedLabel(fields: MetadataField[] | undefined, t: TFunc): string | null {
  if (!fields?.length) return null;
  return fields.map((field) => t(`uploadResults.fields.${field}`)).join(", ");
}

export function UploadResultsModal({ results, onClose, noun = "files" }: { results: UploadFileResult[]; onClose: () => void; noun?: "images" | "files" }) {
  const t = useTranslations("files");
  return (
    <Modal open title={t("uploadResults.title")} description={uploadResultsSummary(results, t, noun)} onClose={onClose}>
      <ul className="upload-results-list">
        {results.map((result, index) => {
          const applied = appliedLabel(result.applied, t);
          const failure = result.status === "failed" ? uploadFailureText(result, t) : null;
          return (
            <li key={`${result.name}-${index}`} className="upload-results-row">
              <span className="upload-results-name" title={result.name}>{result.name}</span>
              <Badge variant={STATUS_VARIANT[result.status]}>{t(`uploadResults.status.${result.status}`)}</Badge>
              {applied && <span className="upload-results-detail">{t("uploadResults.appliedDetail", { fields: applied })}</span>}
              {failure && <span className="upload-results-detail">{failure}</span>}
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}
