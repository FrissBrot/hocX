import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("documentStudio.pdfLoading");
  return { title: `${t("title")} · hocX` }; // i18n-ok: Trennzeichen und Produktname im Tab-Titel
}

/** Platzhalter im neuen Tab, solange ein PDF erzeugt wird (use-pdf-export.ts, export-dialog.tsx).
 * Der aufrufende Tab ersetzt die Seite per location.replace durch das fertige PDF. Reines CSS,
 * kein Client-JavaScript: erscheint sofort, auch während der Server rendert. */
export default async function PdfLoadingPage() {
  const t = await getTranslations("documentStudio.pdfLoading");
  return (
    <main className="pdf-wait">
      <div className="pdf-wait-sheet" aria-hidden="true">
        <span className="pdf-wait-line pdf-wait-line-title" />
        <span className="pdf-wait-line" />
        <span className="pdf-wait-line" />
        <span className="pdf-wait-line pdf-wait-line-short" />
        <span className="pdf-wait-line" />
        <span className="pdf-wait-line" />
        <span className="pdf-wait-line pdf-wait-line-short" />
        <span className="pdf-wait-scan" />
      </div>
      <div className="pdf-wait-text" role="status" aria-live="polite">
        <h1 className="pdf-wait-title">{t("title")}</h1>
        <p className="muted">{t("message")}</p>
        <div className="pdf-wait-bar" aria-hidden="true">
          <span />
        </div>
        <p className="field-help">{t("hint")}</p>
      </div>
    </main>
  );
}
