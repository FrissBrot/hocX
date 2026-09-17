"use client";

import { useCallback, useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import { FileStats } from "@/types/api";

export function FileStatCards() {
  const [stats, setStats] = useState<FileStats | null>(null);
  // Distinguishes "haven't loaded yet"/"genuinely zero files" from "the request failed" -
  // the no-op .catch() below used to swallow any error, leaving the whole KPI row blank
  // forever with no way to tell which of those it was, and no retry (audit fix,
  // 2026-09-17).
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    browserApiFetch<FileStats>("/api/files/stats")
      .then((data) => setStats(data ?? null))
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <p className="form-error-banner">
        Statistik konnte nicht geladen werden.{" "}
        <button type="button" className="button-inline button-ghost" onClick={load}>
          Erneut versuchen
        </button>
      </p>
    );
  }

  if (!stats) return null;

  return (
    <div className="stats-kpi-row">
      <div className="stats-card">
        <span className="stats-card-label">Dokumente</span>
        <span className="stats-card-value">{stats.document_count}</span>
      </div>
      <div className="stats-card">
        <span className="stats-card-label">Fotos</span>
        <span className="stats-card-value">{stats.photo_count}</span>
      </div>
      <div className="stats-card">
        <span className="stats-card-label">Speicher</span>
        <span className="stats-card-value">{formatFileSize(stats.total_bytes)}</span>
      </div>
    </div>
  );
}
