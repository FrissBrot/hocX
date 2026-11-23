"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch, LONG_RUNNING_TIMEOUT_MS } from "@/lib/api/client";
import {
  apiErrorCode,
  cleanRule,
  moveItem,
  newRule,
  type ImportJob,
  type ImportPreview,
  type ImportRule,
  type ImportTypeFilter,
} from "@/lib/files/file-import";
import { formatDate, formatFileSize, formatInteger } from "@/lib/utils/format";

import { ImportRuleCard, type AlbumOption } from "./import-rule-card";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 400;

type View = "all" | "import" | "skipped" | "conflicts";

type Props = {
  job: ImportJob;
  readOnly: boolean;
  onJob: (job: ImportJob) => void;
  onCancelled: () => void | Promise<void>;
};

export function ImportRulesStep({ job, readOnly, onJob, onCancelled }: Props) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [rules, setRules] = useState<ImportRule[]>(() => job.rules ?? []);
  const [typeFilter, setTypeFilter] = useState<ImportTypeFilter>(job.type_filter);
  const [includeGps, setIncludeGps] = useState(job.include_gps);
  const [folderTags, setFolderTags] = useState(job.folder_tags);
  const [albumsEnabled, setAlbumsEnabled] = useState(job.albums_enabled);
  const [view, setView] = useState<View>("all");
  const [ruleFilter, setRuleFilter] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [albums, setAlbums] = useState<AlbumOption[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const requestId = useRef(0);
  // Nur der Text, nicht t selbst als Abhängigkeit: sonst rechnet jede neue t-Instanz die Vorschau neu.
  const genericError = useRef(t("errors.generic"));

  useEffect(() => {
    void browserApiFetch<{ id: string; name: string; kind: string }[]>("/api/files/albums")
      .then((list) => setAlbums(list.filter((album) => album.kind === "manual").map(({ id, name }) => ({ id, name }))))
      .catch(() => setAlbums([]));
    void browserApiFetch<string[]>("/api/files/tags").then(setTagSuggestions).catch(() => setTagSuggestions([]));
  }, []);

  const body = useMemo(
    () => ({
      rules: rules.map(cleanRule),
      type_filter: typeFilter,
      include_gps: includeGps,
      folder_tags: folderTags,
      albums_enabled: albumsEnabled,
      view,
      rule_id: ruleFilter || null,
      q: query.trim() || null,
      offset,
      limit: PAGE_SIZE,
    }),
    [rules, typeFilter, includeGps, folderTags, albumsEnabled, view, ruleFilter, query, offset],
  );

  useEffect(() => {
    const current = ++requestId.current;
    setLoading(true);
    const timer = window.setTimeout(() => {
      browserApiFetch<ImportPreview>(`/api/cloud-import/jobs/${job.id}/preview`, {
        method: "POST",
        timeoutMs: LONG_RUNNING_TIMEOUT_MS,
        body: JSON.stringify(body),
      })
        .then((result) => {
          if (current === requestId.current) setPreview(result);
        })
        .catch((error) => {
          if (current === requestId.current) showToast(error instanceof Error ? error.message : genericError.current, "error");
        })
        .finally(() => {
          if (current === requestId.current) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [body, job.id, showToast]);

  function updateRules(next: ImportRule[]) {
    setRules(next);
    setOffset(0);
  }

  async function handleStart() {
    if (!preview) return;
    const ok = await confirm({
      message: t("start.confirm", { count: preview.summary.importable, size: formatFileSize(preview.summary.planned_bytes, locale) }),
      confirmLabel: t("start.label"),
    });
    if (!ok) return;
    setStarting(true);
    try {
      onJob(await browserApiFetch<ImportJob>(`/api/cloud-import/jobs/${job.id}/start`, { method: "POST", timeoutMs: LONG_RUNNING_TIMEOUT_MS }));
    } catch (error) {
      const code = apiErrorCode(error);
      showToast(code && t.has(`errors.${code}`) ? t(`errors.${code}`) : error instanceof Error ? error.message : t("errors.generic"), "error");
    } finally {
      setStarting(false);
    }
  }

  async function handleCancel() {
    const ok = await confirm({ tone: "danger", message: t("cancel.draftConfirm"), confirmLabel: t("cancel.label") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/cloud-import/jobs/${job.id}/cancel`, { method: "POST" });
      await onCancelled();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errors.generic"), "error");
    }
  }

  const summary = preview?.summary;
  const hasErrors = (preview?.errors.length ?? 0) > 0;
  const quota = preview?.quota;
  const skippedTotal = summary ? Object.values(summary.skipped).reduce((sum, value) => sum + value, 0) : 0;
  const ruleLabel = (id: string) => {
    const index = rules.findIndex((rule) => rule.id === id);
    return index >= 0 ? t("rules.ruleTitle", { number: index + 1 }) : id;
  };

  return (
    <div className="grid file-import-rules-step">
      <section className="section-card file-import-card">
        <div className="file-import-card-head">
          <div>
            <h2 className="section-title">{t("rules.title")}</h2>
            <p className="muted">{t("rules.intro")}</p>
          </div>
          {readOnly ? null : (
            <button type="button" className="button-secondary" onClick={() => updateRules([...rules, newRule()])} disabled={rules.length >= 50}>
              {t("rules.add")}
            </button>
          )}
        </div>
        <div className="grid file-import-options">
          <label className="field-stack">
            <span className="field-label">{t("options.typeFilter")}</span>
            <Select value={typeFilter} disabled={readOnly} onChange={(event) => { setTypeFilter(event.target.value as ImportTypeFilter); setOffset(0); }}>
              <option value="all">{t("options.types.all")}</option>
              <option value="images">{t("options.types.images")}</option>
              <option value="documents">{t("options.types.documents")}</option>
            </Select>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={includeGps} disabled={readOnly} onChange={(event) => setIncludeGps(event.target.checked)} />
            {t("options.includeGps")}
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={folderTags} disabled={readOnly} onChange={(event) => { setFolderTags(event.target.checked); setOffset(0); }} />
            {t("options.folderTags")}
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={albumsEnabled} disabled={readOnly} onChange={(event) => { setAlbumsEnabled(event.target.checked); setOffset(0); }} />
            {t("options.albumsEnabled")}
          </label>
        </div>
        <p className="field-help">{t("options.albumsHint")}</p>
        {rules.length === 0 ? <p className="muted">{t("rules.empty")}</p> : null}
        <div className="file-import-rule-list">
          {rules.map((rule, index) => (
            <ImportRuleCard
              key={rule.id}
              rule={rule}
              index={index}
              count={rules.length}
              matches={summary?.per_rule[rule.id] ?? (summary ? 0 : undefined)}
              errors={preview?.errors.filter((error) => error.rule_id === rule.id) ?? []}
              folders={preview?.folders ?? []}
              albums={albums}
              tagSuggestions={tagSuggestions}
              albumsEnabled={albumsEnabled}
              readOnly={readOnly}
              onChange={(next) => updateRules(rules.map((entry) => (entry.id === rule.id ? next : entry)))}
              onMove={(from, to) => updateRules(moveItem(rules, from, to))}
              onRemove={() => updateRules(rules.filter((entry) => entry.id !== rule.id))}
            />
          ))}
        </div>
      </section>

      <section className="section-card file-import-card" aria-busy={loading}>
        <h2 className="section-title">{t("preview.title")}</h2>
        {summary ? (
          <div className="file-import-stats">
            <span><strong>{formatInteger(summary.importable, locale)}</strong> {t("preview.toImport")}</span>
            <span>{t("preview.kinds", { images: summary.images, documents: summary.documents })}</span>
            <span>{formatFileSize(summary.planned_bytes, locale)}</span>
            <span>{t("preview.skipped", { count: skippedTotal })}</span>
            {summary.conflicts ? <Badge variant="warning">{t("preview.conflicts", { count: summary.conflicts })}</Badge> : null}
          </div>
        ) : null}
        {summary && skippedTotal ? (
          <p className="muted">
            {Object.entries(summary.skipped)
              .map(([code, count]) => `${t.has(`codes.${code}`) ? t(`codes.${code}`) : code}: ${formatInteger(count, locale)}`)
              .join(" · ")}
          </p>
        ) : null}
        {quota && !quota.fits ? (
          <StatusBanner
            tone="error"
            message={t("preview.quotaExceeded", {
              planned: formatFileSize(quota.planned_bytes, locale),
              free: formatFileSize(Math.max(0, (quota.limit_bytes ?? 0) - quota.used_bytes), locale),
            })}
          />
        ) : null}
        {hasErrors ? <StatusBanner tone="warning" message={t("preview.ruleErrors")} /> : null}
        {albumsEnabled && preview?.existing_albums.length ? (
          <StatusBanner tone="neutral" message={t("preview.existingAlbums", { names: preview.existing_albums.join(", ") })} />
        ) : null}
        {summary?.conflicts ? <StatusBanner tone="neutral" message={t("preview.conflictHint")} /> : null}

        <div className="list-filter-row">
          <FilterTabs<View>
            value={view}
            onChange={(value) => { setView(value); setOffset(0); }}
            options={[
              { value: "all", label: t("preview.views.all") },
              { value: "import", label: t("preview.views.import") },
              { value: "skipped", label: t("preview.views.skipped") },
              { value: "conflicts", label: t("preview.views.conflicts") },
            ]}
          />
          <Select value={ruleFilter} aria-label={t("preview.ruleFilter")} onChange={(event) => { setRuleFilter(event.target.value); setOffset(0); }}>
            <option value="">{t("preview.allRules")}</option>
            {rules.map((rule) => (
              <option key={rule.id} value={rule.id}>{ruleLabel(rule.id)}</option>
            ))}
          </Select>
          <SearchInput value={query} onChange={(value) => { setQuery(value); setOffset(0); }} placeholder={t("preview.search")} />
        </div>
        <DataTable
          columns={[t("preview.columns.path"), t("preview.columns.result"), t("preview.columns.tags"), t("preview.columns.date"), t("preview.columns.albums"), t("preview.columns.rules")]}
          emptyMessage={loading ? t("preview.loading") : t("preview.empty")}
        >
          {(preview?.items ?? []).map((item) => (
            <tr key={item.path}>
              <td className="file-import-path">{item.path}</td>
              <td>
                {item.import ? (
                  <Badge variant="success">{t(`kinds.${item.kind}`)}</Badge>
                ) : (
                  <Badge variant="neutral">{item.reason && t.has(`codes.${item.reason}`) ? t(`codes.${item.reason}`) : t("preview.notImported")}</Badge>
                )}
                {item.conflict ? <Badge variant="warning">{t("preview.conflict")}</Badge> : null}
              </td>
              <td>{item.tags.join(", ")}</td>
              <td>
                {item.date ? formatDate(item.date) : ""}
                {item.date && item.date_source === "takeout" ? <span className="muted"> ({t("preview.fromTakeout")})</span> : null}
              </td>
              <td>{item.albums.join(", ")}</td>
              <td>{item.rules.map(ruleLabel).join(", ")}</td>
            </tr>
          ))}
        </DataTable>
        {preview ? <Pagination offset={offset} limit={PAGE_SIZE} total={preview.filtered_total} onOffsetChange={setOffset} /> : null}

        {readOnly ? null : (
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => void handleCancel()}>{t("cancel.label")}</button>
            <button
              type="button"
              className="button-primary"
              disabled={starting || loading || !preview || hasErrors || !preview.saved || preview.summary.importable === 0 || !preview.quota.fits}
              onClick={() => void handleStart()}
            >
              {t("start.label")}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
