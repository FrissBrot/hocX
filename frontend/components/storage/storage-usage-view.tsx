"use client";

import { formatFileSize } from "@/lib/utils/format";
import { StorageCategoryKey, StorageUsageRead } from "@/types/api";

type Props = {
  usage: StorageUsageRead | null;
};

export const CATEGORY_COLORS: Record<StorageCategoryKey, string> = {
  protocol_image: "#6366f1",
  word_import: "#06b6d4",
  submission_upload: "#b45309",
  gallery_upload: "#db2777",
  export: "#a855f7",
  other: "#9ca3af",
};

export function formatPercent(part: number, total: number): string {
  if (total <= 0) return "0%";
  return `${((part / total) * 100).toFixed(part / total >= 0.1 ? 0 : 1)}%`;
}

export function StorageUsageView({ usage }: Props) {
  if (!usage) {
    return (
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">Speicher</h1>
            <p className="muted">Speicherverbrauch dieses Mandanten.</p>
          </div>
        </div>
        <div className="card muted">Speicherdaten konnten nicht geladen werden.</div>
      </div>
    );
  }

  const { total_bytes, quota_bytes, categories } = usage;
  const visibleCategories = categories.filter((c) => c.bytes > 0);
  const barTotal = quota_bytes && quota_bytes > total_bytes ? quota_bytes : total_bytes;
  const overQuota = quota_bytes !== null && total_bytes > quota_bytes;
  const freeBytes = quota_bytes !== null ? Math.max(quota_bytes - total_bytes, 0) : null;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Speicher</h1>
          <p className="muted">Speicherverbrauch dieses Mandanten, aufgeteilt nach Herkunft der Dateien.</p>
        </div>
      </div>

      {overQuota ? (
        <div className="form-error-banner">
          Das Speicherkontingent ist überschritten ({formatFileSize(total_bytes)} von {formatFileSize(quota_bytes)}
          {" "}belegt). Bitte nicht mehr benötigte Dateien löschen oder das Kontingent erhöhen lassen.
        </div>
      ) : null}

      <div className="stats">
        <div className="stats-card">
          <div className="stats-card-label">Belegt</div>
          <div className="stats-card-value">{formatFileSize(total_bytes)}</div>
        </div>
        <div className="stats-card">
          <div className="stats-card-label">Kontingent</div>
          <div className="stats-card-value">{quota_bytes !== null ? formatFileSize(quota_bytes) : "Kein Limit"}</div>
        </div>
        <div className="stats-card">
          <div className="stats-card-label">Frei</div>
          <div className="stats-card-value">{freeBytes !== null ? formatFileSize(freeBytes) : "—"}</div>
          {overQuota ? <div className="stats-card-sub">Kontingent überschritten</div> : null}
        </div>
      </div>

      <article className="card grid">
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

        <div className="table-shell">
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
                    </td>
                    <td>{formatFileSize(category.bytes)}</td>
                    <td className="muted">{formatPercent(category.bytes, total_bytes)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </article>
    </div>
  );
}
