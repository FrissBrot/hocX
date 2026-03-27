"use client";

import { useState } from "react";

import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
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
  initialLatestExport
}: {
  protocol: ProtocolSummary;
  initialLatestExport: ProtocolExport;
}) {
  const [latestExport, setLatestExport] = useState(initialLatestExport);
  const [status, setStatus] = useState("Ready");

  async function runExport(format: "latex" | "pdf") {
    setStatus(`Generating ${format.toUpperCase()}...`);
    try {
      const result = await browserApiFetch<ProtocolExport>(`/api/protocols/${protocol.id}/exports/${format}`, {
        method: "POST"
      });
      setLatestExport(result);
      setStatus(`${format.toUpperCase()} generated`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Export failed");
    }
  }

  return (
    <article className="card">
      <div className="eyebrow">Export</div>
      <h3>LaTeX and PDF</h3>
      <div className="status-row">
        <button type="button" onClick={() => runExport("latex")}>
          Generate LaTeX
        </button>
        <button type="button" onClick={() => runExport("pdf")}>
          Generate PDF
        </button>
      </div>
      <p className="muted">{status}</p>
      <p className="muted">
        Latest export: {latestExport.export_format} · {latestExport.status}
      </p>
      {latestExport.content_url ? (
        <a href={`${browserApiBaseUrl}${latestExport.content_url}`} target="_blank" rel="noreferrer">
          Download latest export
        </a>
      ) : (
        <p className="muted">No export generated yet.</p>
      )}
    </article>
  );
}
