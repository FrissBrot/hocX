"use client";

import { useTranslations } from "next-intl";

import type { UploadPhase } from "@/lib/upload-request";

// Fortschritt während des Uploads: Balken mit Prozent, solange Bytes gesendet werden, danach
// unbestimmter Balken «wird geprüft», bis die Antwort des Servers (Virenprüfung, Ablage) kommt.
// Der Balken trägt role="progressbar" mit aria-valuenow; Screenreader bekommen den Phasenwechsel
// über die role="status"-Zeile angesagt, nicht jeden einzelnen Prozentschritt.
export function UploadProgress({ progress }: { progress: UploadPhase }) {
  const t = useTranslations("abgabebox.upload");
  const uploading = progress.phase === "uploading";
  const percent = uploading ? progress.percent : 100;

  return (
    <div className={`upload-progress${uploading ? "" : " upload-progress-processing"}`}>
      <div className="upload-progress-head">
        <span className="upload-progress-label" role="status">
          {uploading ? t("progressUploading") : t("progressProcessing")}
        </span>
        {uploading ? (
          <span className="upload-progress-value" aria-hidden="true">
            {t("progressPercent", { percent })}
          </span>
        ) : null}
      </div>
      <div
        className="upload-progress-track"
        role="progressbar"
        aria-label={t("progressLabel")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={uploading ? percent : undefined}
        aria-valuetext={uploading ? t("progressPercent", { percent }) : t("progressProcessing")}
      >
        {/* Breite ist ein Laufzeitwert (DESIGN.md 1.5) */}
        <span className="upload-progress-fill" style={{ width: `${percent}%` }} />
      </div>
      {uploading ? null : <p className="upload-progress-hint">{t("progressProcessingHint")}</p>}
    </div>
  );
}
