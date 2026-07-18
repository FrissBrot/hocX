"use client";

import { useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { ProtocolSummary } from "@/types/api";

type ProtocolExport = {
  protocol_id: number;
  export_format: string;
  generated_file_id?: number | null;
  content_url?: string | null;
  storage_path?: string | null;
  created_at?: string | null;
  status: string;
};

export function ProtocolExportPanel({
  protocol,
  initialLatestExport,
}: {
  protocol: ProtocolSummary;
  initialLatestExport: ProtocolExport;
}) {
  const [latestExport, setLatestExport] = useState(
    initialLatestExport.export_format === "pdf"
      ? initialLatestExport
      : { ...initialLatestExport, export_format: "pdf", status: "missing", content_url: null }
  );
  const [status, setStatus] = useState<string | null>(null);

  async function runExport() {
    setStatus("Generiere PDF…");
    try {
      const result = await browserApiFetch<ProtocolExport>(
        `/api/protocols/${protocol.id}/exports/pdf`,
        { method: "POST" }
      );
      setLatestExport(result);
      setStatus(null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Export fehlgeschlagen");
    }
  }

  return (
    <article className="card">
      <div className="eyebrow">Exporte</div>
      <div style={{ marginTop: "12px" }}>
        <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="button-inline" onClick={runExport}>
            Protokoll-PDF generieren
          </button>
          {latestExport.content_url && (
            <a
              href={`${latestExport.content_url}?download=1`}
              target="_blank"
              rel="noreferrer"
              className="button-inline"
              style={{ textDecoration: "none" }}
            >
              Protokoll-PDF herunterladen
            </a>
          )}
        </div>
        <p className="muted" style={{ fontSize: "0.82rem", marginTop: "4px" }}>
          {latestExport.status === "missing"
            ? "Noch kein Export vorhanden."
            : `Letzter Export: ${latestExport.created_at ? new Date(latestExport.created_at).toLocaleString("de-CH") : "—"}`}
        </p>
        {status && (
          <p className="muted" style={{ fontSize: "0.82rem", color: status.includes("fehl") ? "var(--danger)" : undefined }}>
            {status}
          </p>
        )}
      </div>
    </article>
  );
}
