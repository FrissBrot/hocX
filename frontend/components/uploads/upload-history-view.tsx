"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Select } from "@/components/ui/select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ALL_CHANNELS, FILE_CHANNELS, PHOTO_CHANNELS } from "@/lib/uploads/upload-jobs";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import type { UploadChannel, UploadJob, UploadJobList } from "@/types/api";

import { actorLabel, resultSummary, UploadStatusBadge } from "./upload-labels";

const PAGE_SIZE = 50;

/** Upload-Verlauf (/photos/uploads, /files/uploads): eine Komponente, Kanalfilter je Bereich vorbelegt.
 * Keyset-Paginierung («Mehr laden»), keine Gesamtzahl. */
export function UploadHistoryView({ area, canSeeAll }: { area: "photos" | "files"; canSeeAll: boolean }) {
  const t = useTranslations("uploads");
  const locale = useLocale();
  const showToast = useToast();
  const basePath = `/${area}/uploads`;
  const [scope, setScope] = useState<"mine" | "all">(canSeeAll ? "all" : "mine");
  const [channel, setChannel] = useState<"area" | UploadChannel>("area");
  const [problemsOnly, setProblemsOnly] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const requestRef = useRef(0);

  function query(next: string | null) {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
    if (scope === "mine") params.set("mine", "true");
    (channel === "area" ? (area === "photos" ? PHOTO_CHANNELS : FILE_CHANNELS) : [channel]).forEach((value) => params.append("channel", value));
    if (problemsOnly) params.set("problems", "true");
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (next) params.set("cursor", next);
    return `/api/upload-jobs?${params.toString()}`;
  }

  async function load(more: boolean) {
    const request = ++requestRef.current;
    setLoading(true);
    try {
      const list = await browserApiFetch<UploadJobList>(query(more ? cursor : null));
      if (request !== requestRef.current) return;
      setJobs((current) => (more ? [...current, ...(list?.items ?? [])] : list?.items ?? []));
      setCursor(list?.next_cursor ?? null);
    } catch (error) {
      if (request === requestRef.current) showToast(error instanceof Error && error.message ? error.message : t("loadError"), "error");
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  }

  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, channel, problemsOnly, dateFrom, dateTo]);

  return (
    <div className="grid upload-history">
      <div className="page-header">
        <div>
          <Link className="upload-history-back" href={`/${area}`}>{t(area === "photos" ? "backToPhotos" : "backToFiles")}</Link>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t(area === "photos" ? "descriptionPhotos" : "descriptionFiles")}</p>
        </div>
      </div>
      <div className="list-filter-row upload-history-filters">
        {canSeeAll ? (
          <FilterTabs<"mine" | "all">
            options={[
              { value: "all", label: t("filter.all") },
              { value: "mine", label: t("filter.mine") },
            ]}
            value={scope}
            onChange={setScope}
          />
        ) : null}
        <label className="field-stack upload-history-channel">
          <span className="field-label">{t("filter.channel")}</span>
          <Select value={channel} onChange={(event) => setChannel(event.target.value as "area" | UploadChannel)}>
            <option value="area">{t(area === "photos" ? "filter.areaPhotos" : "filter.areaFiles")}</option>
            {ALL_CHANNELS.map((value) => (
              <option key={value} value={value}>{t(`channel.${value}`)}</option>
            ))}
          </Select>
        </label>
        <div className="two-col upload-history-dates">
          <label className="field-stack">
            <span className="field-label">{t("filter.from")}</span>
            <DateInput value={dateFrom} onChange={setDateFrom} aria-label={t("filter.from")} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("filter.to")}</span>
            <DateInput value={dateTo} onChange={setDateTo} aria-label={t("filter.to")} />
          </label>
        </div>
        <label className="upload-history-problems">
          <input type="checkbox" checked={problemsOnly} onChange={(event) => setProblemsOnly(event.target.checked)} />
          {t("filter.problemsOnly")}
        </label>
      </div>
      <DataTable
        columns={[t("column.time"), t("column.person"), t("column.channel"), t("column.ref"), t("column.result"), t("column.status")]}
        emptyMessage={loading ? t("loading") : t("empty")}
      >
        {jobs.map((job) => (
          <tr key={job.id}>
            <td>
              <Link className="table-row-link" href={`${basePath}/${job.id}`}>{formatDateTime(job.created_at, locale)}</Link>
              {job.reconstructed ? <span className="muted upload-history-note">{t("reconstructed")}</span> : null}
            </td>
            <td>{actorLabel(job, t)}</td>
            <td><Badge variant="neutral">{t(`channel.${job.channel}`)}</Badge></td>
            <td>{job.ref ? [job.ref.label ?? t(`ref.${job.ref.kind}`), job.ref.on_date ? formatDate(job.ref.on_date) : null].filter(Boolean).join(" · ") : "–"}</td>
            <td>{resultSummary(job, t)}</td>
            <td><UploadStatusBadge status={job.status} /></td>
          </tr>
        ))}
      </DataTable>
      {cursor ? (
        <div className="load-more-row">
          <button type="button" className="button-secondary button-ghost" disabled={loading} onClick={() => void load(true)}>{t("loadMore")}</button>
        </div>
      ) : null}
    </div>
  );
}
