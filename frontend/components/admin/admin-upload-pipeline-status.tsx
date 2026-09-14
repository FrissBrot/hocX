"use client";

import { useEffect, useRef, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import {
  AdminTenantSummary,
  UploadPipelineFileEntry,
  UploadPipelineOverview,
  UploadPipelineSource,
} from "@/types/api";

type Props = {
  initialOverview: UploadPipelineOverview;
  tenants: AdminTenantSummary[];
};

const PAGE_SIZE = 50;
// Refetch on a timer, not just on filter/page change - unlike the Fehlerprotokoll page,
// "wo stehen Dateien gerade" is by definition a live/moving state (a file goes
// pending -> clean within seconds of the next rescan sweep), so a stale snapshot the admin
// has to manually refresh would defeat the point of the view.
const POLL_INTERVAL_MS = 15_000;

const SOURCE_LABELS: Record<UploadPipelineSource, string> = {
  protocol_image: "Protokollbild",
  gallery_upload: "Galerie",
  word_import: "Word-Import",
  submission_upload: "Abgabe",
};

const SCAN_STATUS_LABELS: Record<string, string> = {
  clean: "Sauber",
  pending: "Prüfung ausstehend",
  infected: "Infiziert",
};

const SCAN_STATUS_VARIANTS: Record<string, BadgeVariant> = {
  clean: "success",
  pending: "warning",
  infected: "danger",
};

function scanStatusVariant(status: string): BadgeVariant {
  return SCAN_STATUS_VARIANTS[status] ?? "neutral";
}

function scanStatusLabel(status: string): string {
  return SCAN_STATUS_LABELS[status] ?? status;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
}

export function AdminUploadPipelineStatus({ initialOverview, tenants }: Props) {
  const [overview, setOverview] = useState(initialOverview);
  const [tenantId, setTenantId] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [scanStatus, setScanStatus] = useState<string>("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const loadingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      // Skip an overlapping poll tick while the previous request (or a just-triggered
      // filter-change request) is still in flight, rather than piling up requests.
      if (loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (tenantId) params.set("tenant_id", tenantId);
        if (source) params.set("source", source);
        if (scanStatus) params.set("scan_status", scanStatus);
        params.set("limit", String(PAGE_SIZE));
        params.set("offset", String(offset));
        const result = await browserApiFetch<UploadPipelineOverview>(`/api/admin/upload-pipeline-status?${params.toString()}`);
        if (!cancelled) setOverview(result);
      } catch {
        // keep showing the previous snapshot rather than blanking the view on a transient error
      } finally {
        loadingRef.current = false;
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    const interval = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [tenantId, source, scanStatus, offset]);

  function resetAndSet(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      setOffset(0);
    };
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Datei-Pipeline"
        description="Wo Dateien aus allen Upload-Wegen (Protokollbild, Galerie, Word-Import, Abgabebox) gerade stehen - Scan-Ergebnis und Herkunft je Datei, aktualisiert alle 15 Sekunden."
      />

      <article className="card">
        <div className="filter-row" style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {overview.summary.map((entry) => (
            <Badge key={`${entry.source}-${entry.scan_status}`} variant={scanStatusVariant(entry.scan_status)}>
              {SOURCE_LABELS[entry.source] ?? entry.source} · {scanStatusLabel(entry.scan_status)}: {entry.count}
            </Badge>
          ))}
          {overview.summary.length === 0 && <span className="muted">Noch keine Uploads.</span>}
        </div>
      </article>

      <article className="card">
        <div className="filter-row" style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <label className="field-stack">
            <span className="field-label">Mandant</span>
            <SearchableSelect
              options={tenants}
              getId={(t) => String(t.id)}
              getLabel={(t) => t.name}
              value={tenantId || null}
              onChange={(t) => resetAndSet(setTenantId)(t ? String(t.id) : "")}
              nullLabel="Alle"
            />
          </label>
          <label className="field-stack">
            <span className="field-label">Herkunft</span>
            <SearchableSelect
              options={Object.keys(SOURCE_LABELS)}
              getId={(s) => s}
              getLabel={(s) => SOURCE_LABELS[s as UploadPipelineSource] ?? s}
              value={source || null}
              onChange={(s) => resetAndSet(setSource)(s ?? "")}
              nullLabel="Alle"
            />
          </label>
          <label className="field-stack">
            <span className="field-label">Status</span>
            <SearchableSelect
              options={Object.keys(SCAN_STATUS_LABELS)}
              getId={(s) => s}
              getLabel={(s) => SCAN_STATUS_LABELS[s] ?? s}
              value={scanStatus || null}
              onChange={(s) => resetAndSet(setScanStatus)(s ?? "")}
              nullLabel="Alle"
            />
          </label>
        </div>
      </article>

      <DataTable
        columns={["Zeitpunkt", "Mandant", "Herkunft", "Datei", "Grösse", "Status"]}
        emptyMessage={loading ? "Wird geladen…" : "Keine Dateien gefunden."}
      >
        {overview.files.items.map((item) => (
          <FileRow key={item.id} item={item} />
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={overview.files.total} onOffsetChange={setOffset} />

      <article className="card">
        <DataToolbar
          title="Abgabebox — gerade in Prüfung"
          description="Dateien, die gerade in Quarantäne auf den Virenscan warten und noch keinen Eintrag in der Dateien-Übersicht haben (das passiert erst nach erfolgreichem Scan)."
        />
        {overview.abgabebox_quarantine.length === 0 ? (
          <p className="muted">Keine Dateien gerade in Prüfung.</p>
        ) : (
          <DataTable columns={["Mandant", "Abgabe", "Datei", "Grösse", "Alter"]}>
            {overview.abgabebox_quarantine.map((entry, index) => (
              <tr key={`${entry.tenant_id ?? "?"}-${entry.assignment_id ?? "?"}-${entry.file_name}-${index}`}>
                <td>{entry.tenant_name ?? <span className="muted">Unbekannt</span>}</td>
                <td className="muted">{entry.assignment_id ?? "—"}</td>
                <td>{entry.file_name}</td>
                <td className="muted">{formatBytes(entry.file_size_bytes)}</td>
                <td>
                  <Badge variant="warning">{formatAge(entry.age_seconds)}</Badge>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </article>
    </div>
  );
}

function FileRow({ item }: { item: UploadPipelineFileEntry }) {
  return (
    <tr>
      <td className="muted">{new Date(item.created_at).toLocaleString("de-CH")}</td>
      <td>{item.tenant_name}</td>
      <td>{item.origin_tag}</td>
      <td>{item.original_name}</td>
      <td className="muted">{formatBytes(item.file_size_bytes)}</td>
      <td>
        <Badge variant={scanStatusVariant(item.scan_status)}>{scanStatusLabel(item.scan_status)}</Badge>
      </td>
    </tr>
  );
}
