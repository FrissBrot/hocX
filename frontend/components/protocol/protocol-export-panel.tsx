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
  initialLatestExport
}: {
  protocol: ProtocolSummary;
  initialLatestExport: ProtocolExport;
}) {
  const [latestExport, setLatestExport] = useState(
    initialLatestExport.export_format === "pdf"
      ? initialLatestExport
      : { ...initialLatestExport, export_format: "pdf", status: "missing", content_url: null, generated_file_id: null }
  );
  const [status, setStatus] = useState("Ready");

  async function runExport() {
    setStatus("Generating PDF...");
    try {
      const result = await browserApiFetch<ProtocolExport>(`/api/protocols/${protocol.id}/exports/pdf`, {
        method: "POST"
      });
      setLatestExport(result);
      setStatus("PDF generated");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Export failed");
    }
  }

  return (
    <article className="card">
      <div className="eyebrow">PDF Export</div>
      <h3>Create PDF</h3>
      <div className="status-row">
        <button type="button" onClick={runExport}>
          Generate PDF
        </button>
      </div>
      <p className="muted">{status}</p>
      <p className="muted">Latest PDF export: {latestExport.status}</p>
      <p className="muted">
        The PDF download is available from the protocol table.
      </p>
    </article>
  );
}
