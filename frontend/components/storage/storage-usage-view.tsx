"use client";

import { formatFileSize } from "@/lib/utils/format";
import { StorageCategoryKey, StorageUsageRead } from "@/types/api";

export const CATEGORY_COLORS: Record<StorageCategoryKey, string> = {
  photos: "#db2777",
  files: "#6366f1",
  protocols: "#0d9488",
  other: "#9ca3af",
};

export const CATEGORY_HINTS: Record<StorageCategoryKey, string> = {
  photos: "Galerie, Protokoll-Bilder und Abgabebox-Bilder",
  files: "Word-Importe, Abgabebox-Dokumente und weitere Uploads",
  protocols: "Erzeugte PDF-/LaTeX-Exporte",
  other: "Logos, Importe und übrige Dateien",
};

export function formatPercent(part: number, total: number): string {
  if (total <= 0) return "0%";
  return `${((part / total) * 100).toFixed(part / total >= 0.1 ? 0 : 1)}%`;
}

/** Wie sich das Speicherkontingent zusammensetzt (Plan-Anteil + Zusatzpakete,
 * 0087_storage_packages) - eigenständig von der Nutzungs-Aufschlüsselung oben (Fotos/Dateien/…),
 * weil sie das Kontingent selbst erklärt statt dessen Belegung. Einmal hier definiert, damit
 * Admin-Tenant-Modal und Mandanten-Abo-Tab dieselbe Aufschlüsselung zeigen. */
export function StorageQuotaComposition({
  planStorageBytes,
  packageStorageBytes,
  manualOverride,
}: {
  planStorageBytes: number | null;
  packageStorageBytes: number;
  manualOverride: boolean;
}) {
  if (manualOverride) {
    return <div className="muted">Manuell gesetztes Kontingent (nicht aus Abo/Paketen berechnet)</div>;
  }
  if (planStorageBytes === null && packageStorageBytes === 0) {
    return null;
  }
  return (
    <div className="muted">
      {formatFileSize(planStorageBytes ?? 0)} aus Abo
      {packageStorageBytes > 0 ? ` + ${formatFileSize(packageStorageBytes)} aus Zusatzpaketen` : ""}
    </div>
  );
}

/** The usage bar (with a free-space segment once a quota is set) plus its Kategorie/
 * Grösse/Anteil legend table - shared between the tenant-facing Speicher page (below)
 * and the admin tenant-settings "Speicher" tab, which used to hand-roll its own copy of
 * both (audit fix, 2026-09-17). That copy had drifted from this one: it computed the
 * bar's denominator as `Math.max(total, quota, 1)` instead of this component's
 * `quota > total ? quota : total`, and had no free-space segment at all - so an
 * over-quota tenant rendered a different bar (and no "over quota" visual) to an admin
 * than to the tenant themselves for the exact same numbers. */
export function StorageBreakdown({ total_bytes, quota_bytes, categories }: StorageUsageRead) {
  const visibleCategories = categories.filter((c) => c.bytes > 0);
  const barTotal = quota_bytes && quota_bytes > total_bytes ? quota_bytes : total_bytes;
  const freeBytes = quota_bytes !== null ? Math.max(quota_bytes - total_bytes, 0) : null;

  return (
    <>
      <div className="storage-usage-bar">
        {barTotal > 0
          ? visibleCategories.map((category) => (
              <div
                key={category.key}
                className="storage-usage-segment"
                style={{
                  width: `${(category.bytes / barTotal) * 100}%`,
                  background: CATEGORY_COLORS[category.key],
                }}
                title={`${category.label}: ${formatFileSize(category.bytes)}`}
              />
            ))
          : null}
        {quota_bytes !== null && freeBytes !== null && freeBytes > 0 ? (
          <div className="storage-usage-segment storage-usage-segment-free" style={{ width: `${(freeBytes / barTotal) * 100}%` }} />
        ) : null}
      </div>

      <div className="table-shell storage-breakdown-table">
        <table className="data-table">
          <thead>
            <tr>
              <th>Kategorie</th>
              <th>Grösse</th>
              <th>Anteil</th>
            </tr>
          </thead>
          <tbody>
            {visibleCategories.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  Noch keine Dateien vorhanden.
                </td>
              </tr>
            ) : (
              visibleCategories.map((category) => (
                <tr key={category.key}>
                  <td>
                    <span className="storage-legend-dot" style={{ background: CATEGORY_COLORS[category.key] }} />
                    {category.label}
                    <div className="muted storage-legend-hint">{CATEGORY_HINTS[category.key]}</div>
                  </td>
                  <td>{formatFileSize(category.bytes)}</td>
                  <td className="muted">{formatPercent(category.bytes, total_bytes)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
