import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("documentStudio.pdfLoading");
  return { title: t("tabTitle") };
}

const STEPS = ["collect", "layout", "press", "almost"] as const;

/** Platzhalter im neuen Tab, solange ein PDF erzeugt wird (use-pdf-export.ts, export-dialog.tsx),
 * nach Claude-Design «hocX PDF wird erstellt»: eine Presse setzt drei Blätter zu einem PDF
 * zusammen und stempelt es. Der aufrufende Tab ersetzt die Seite per location.replace durch das
 * fertige PDF. Reines CSS, kein Client-JavaScript: erscheint sofort, auch während der Server rendert. */
export default async function PdfLoadingPage() {
  const t = await getTranslations("documentStudio.pdfLoading");
  return (
    <main className="pdf-wait">
      <div className="pdf-wait-press" aria-hidden="true">
        <div className="pdf-wait-beam" />
        <div className="pdf-wait-post pdf-wait-post-left" />
        <div className="pdf-wait-post pdf-wait-post-right" />
        <div className="pdf-wait-plate">
          <div className="pdf-wait-stem" />
          <div className="pdf-wait-plate-face" />
        </div>
        <div className="pdf-wait-stack">
          <div className="pdf-wait-sheet pdf-wait-sheet-a">
            <span className="pdf-wait-line pdf-wait-w70 pdf-wait-line-strong" />
            <span className="pdf-wait-line pdf-wait-w90" />
            <span className="pdf-wait-line pdf-wait-w82" />
          </div>
          <div className="pdf-wait-sheet pdf-wait-sheet-b">
            <span className="pdf-wait-image" />
            <span className="pdf-wait-line pdf-wait-w92" />
            <span className="pdf-wait-line pdf-wait-w76" />
          </div>
          <div className="pdf-wait-sheet pdf-wait-sheet-c">
            <span className="pdf-wait-heading" />
            <span className="pdf-wait-line pdf-wait-w94" />
            <span className="pdf-wait-line pdf-wait-w86" />
            <span className="pdf-wait-line pdf-wait-w90" />
            <span className="pdf-wait-line pdf-wait-w62" />
            <span className="pdf-wait-ink" />
          </div>
          <div className="pdf-wait-seal">PDF</div>
        </div>
        <span className="pdf-wait-spark pdf-wait-spark-left" />
        <span className="pdf-wait-spark pdf-wait-spark-left pdf-wait-spark-low" />
        <span className="pdf-wait-spark pdf-wait-spark-right" />
        <span className="pdf-wait-spark pdf-wait-spark-right pdf-wait-spark-low" />
        <div className="pdf-wait-base" />
      </div>

      <div className="pdf-wait-text" role="status">
        <h1 className="pdf-wait-title">{t("title")}</h1>
        <div className="pdf-wait-steps">
          {STEPS.map((step) => (
            <span key={step} className={`pdf-wait-step pdf-wait-step-${step}`}>{t(`steps.${step}`)}</span>
          ))}
        </div>
        <div className="pdf-wait-bar" aria-hidden="true">
          <span />
        </div>
        <p className="pdf-wait-hint">{t("hint")}</p>
      </div>

      <div className="pdf-wait-brand">hocX</div>
    </main>
  );
}
