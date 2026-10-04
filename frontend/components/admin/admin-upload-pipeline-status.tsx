"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SOURCE_KEY } from "@/components/files/file-detail-modal";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
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

const SCAN_STATUS_VARIANTS: Record<string, BadgeVariant> = {
  clean: "success",
  pending: "warning",
  error: "danger",
  infected: "danger",
};

function scanStatusVariant(status: string): BadgeVariant {
  return SCAN_STATUS_VARIANTS[status] ?? "neutral";
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
}

export function AdminUploadPipelineStatus({ initialOverview, tenants }: Props) {
  const t = useTranslations("admin.uploadPipeline");
  // Dieselbe Herkunfts->Key-Zuordnung wie file-detail-modal.tsx (SOURCE_KEY), aber ueber den
  // "files"-Namespace uebersetzt - audit fix, 2026-09-17: eine Datei soll in der Admin-Pipeline
  // nicht anders beschriftet sein als in der mandantenseitigen Dateien-Uebersicht.
  const tFiles = useTranslations("files");
  const sourceLabel = (source: UploadPipelineSource | string): string => {
    const key = SOURCE_KEY[source as UploadPipelineSource];
    return key ? tFiles(`source.${key}`) : source;
  };
  const scanStatusLabels: Record<string, string> = {
    clean: t("scanStatus.clean"),
    pending: t("scanStatus.pending"),
    error: t("scanStatus.error"),
    infected: t("scanStatus.infected"),
  };
  function scanStatusLabel(status: string): string {
    return scanStatusLabels[status] ?? status;
  }

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
        title={t("title")}
        description={t("description")}
      />

      <article className="card">
        <div className="filter-row" style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {overview.summary.map((entry) => (
            <Badge key={`${entry.source}-${entry.scan_status}`} variant={scanStatusVariant(entry.scan_status)}>
              {sourceLabel(entry.source)} · {scanStatusLabel(entry.scan_status)}: {entry.count}
            </Badge>
          ))}
          {overview.summary.length === 0 && <span className="muted">{t("noUploadsYet")}</span>}
        </div>
      </article>

      <article className="card">
        <div className="filter-row" style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <label className="field-stack">
            <span className="field-label">{t("tenantLabel")}</span>
            <SearchableSelect
              options={tenants}
              getId={(t) => String(t.id)}
              getLabel={(t) => t.name}
              value={tenantId || null}
              onChange={(t) => resetAndSet(setTenantId)(t ? String(t.id) : "")}
              nullLabel={t("all")}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("originLabel")}</span>
            <SearchableSelect
              options={Object.keys(SOURCE_KEY)}
              getId={(s) => s}
              getLabel={(s) => sourceLabel(s as UploadPipelineSource)}
              value={source || null}
              onChange={(s) => resetAndSet(setSource)(s ?? "")}
              nullLabel={t("all")}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("statusLabel")}</span>
            <SearchableSelect
              options={Object.keys(scanStatusLabels)}
              getId={(s) => s}
              getLabel={(s) => scanStatusLabel(s)}
              value={scanStatus || null}
              onChange={(s) => resetAndSet(setScanStatus)(s ?? "")}
              nullLabel={t("all")}
            />
          </label>
        </div>
      </article>

      <DataTable
        columns={[t("columns.time"), t("columns.tenant"), t("columns.origin"), t("columns.file"), t("columns.size"), t("columns.status")]}
        emptyMessage={loading ? t("loading") : t("emptyFiles")}
      >
        {overview.files.items.map((item) => (
          <FileRow key={item.id} item={item} scanStatusLabel={scanStatusLabel} />
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={overview.files.total} onOffsetChange={setOffset} />

      <article className="card">
        <DataToolbar
          title={t("quarantineTitle")}
          description={t("quarantineDescription")}
        />
        {overview.abgabebox_quarantine.length === 0 ? (
          <p className="muted">{t("noQuarantineFiles")}</p>
        ) : (
          <DataTable columns={[t("quarantineColumns.tenant"), t("quarantineColumns.submission"), t("quarantineColumns.file"), t("quarantineColumns.size"), t("quarantineColumns.age")]}>
            {overview.abgabebox_quarantine.map((entry, index) => (
              <tr key={`${entry.tenant_id ?? "?"}-${entry.assignment_id ?? "?"}-${entry.file_name}-${index}`}>
                <td>{entry.tenant_name ?? <span className="muted">{t("unknown")}</span>}</td>
                <td className="muted">{entry.assignment_id ?? "—"}</td>
                <td>{entry.file_name}</td>
                <td className="muted">{formatFileSize(entry.file_size_bytes)}</td>
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

function FileRow({ item, scanStatusLabel }: { item: UploadPipelineFileEntry; scanStatusLabel: (status: string) => string }) {
  return (
    <tr>
      <td className="muted">{formatDateTime(item.created_at)}</td>
      <td>{item.tenant_name}</td>
      <td>{item.origin_tag}</td>
      <td>{item.original_name}</td>
      <td className="muted">{formatFileSize(item.file_size_bytes)}</td>
      <td>
        <Badge variant={scanStatusVariant(item.scan_status)}>{scanStatusLabel(item.scan_status)}</Badge>
      </td>
    </tr>
  );
}
