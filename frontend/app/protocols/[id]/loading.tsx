import { getTranslations } from "next-intl/server";

// Sofort sichtbares Gerüst des Protokoll-Editors, während page.tsx die Daten lädt (B4): Kopf,
// Gliederung und drei Punkte als Platzhalter. Die Seite streamt danach den fertigen Editor.
export default async function ProtocolLoading() {
  const t = await getTranslations("common");
  return (
    <div className="protocol-loading" role="status" aria-busy="true">
      <span className="visually-hidden">{t("loading")}</span>
      <div className="protocol-loading-head" aria-hidden="true">
        <span className="skeleton skeleton-line protocol-loading-title" />
        <span className="skeleton skeleton-line protocol-loading-meta" />
      </div>
      <div className="protocol-loading-body" aria-hidden="true">
        <div className="protocol-loading-outline">
          {Array.from({ length: 6 }, (_, index) => (
            <span key={index} className="skeleton skeleton-line" />
          ))}
        </div>
        <div className="protocol-loading-doc">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="protocol-loading-section">
              <span className="skeleton skeleton-line protocol-loading-title" />
              <span className="skeleton skeleton-block" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
