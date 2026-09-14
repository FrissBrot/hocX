"use client";

import { useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import { FileStats } from "@/types/api";

export function FileStatCards() {
  const [stats, setStats] = useState<FileStats | null>(null);

  useEffect(() => {
    browserApiFetch<FileStats>("/api/files/stats").then((data) => setStats(data ?? null)).catch(() => {});
  }, []);

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
