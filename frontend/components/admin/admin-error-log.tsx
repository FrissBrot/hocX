"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { TenantPicker } from "@/components/admin/tenant-picker";
import { browserApiFetch } from "@/lib/api/client";
import { SystemErrorLogEntry, SystemErrorLogFilterOptions, SystemErrorLogGroup, SystemErrorLogPage } from "@/types/api";

type Props = {
  initialPage: SystemErrorLogPage;
  initialFilterOptions: SystemErrorLogFilterOptions;
};

const PAGE_SIZE = 50;

const SOURCE_LABELS: Record<string, string> = {
  backend: "hocX",
  "abgabebox-backend": "Abgabebox",
};

export function AdminErrorLog({ initialPage, initialFilterOptions }: Props) {
  const t = useTranslations("admin.errorLog");
  const [page, setPage] = useState(initialPage);
  const [filterOptions] = useState(initialFilterOptions);
  const [tenantId, setTenantId] = useState<string>("");
  const [errorType, setErrorType] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [view, setView] = useState<"entries" | "grouped">("entries");
  const [groups, setGroups] = useState<SystemErrorLogGroup[] | null>(null);
  const locale = useLocale();

  useEffect(() => {
    if (view !== "grouped") return;
    let cancelled = false;
    const params = new URLSearchParams();
    if (tenantId) params.set("tenant_id", tenantId);
    if (source) params.set("source", source);
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    browserApiFetch<SystemErrorLogGroup[]>(`/api/admin/error-logs/groups?${params.toString()}`)
      .then((result) => {
        if (!cancelled) setGroups(result);
      })
      .catch(() => {
        // vorherige Gruppen stehen lassen, wie bei der Liste
      });
    return () => {
      cancelled = true;
    };
  }, [view, tenantId, source, dateFrom, dateTo]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (tenantId) params.set("tenant_id", tenantId);
        if (errorType) params.set("error_type", errorType);
        if (source) params.set("source", source);
        if (dateFrom) params.set("from", dateFrom);
        if (dateTo) params.set("to", dateTo);
        params.set("limit", String(PAGE_SIZE));
        params.set("offset", String(offset));
        const result = await browserApiFetch<SystemErrorLogPage>(`/api/admin/error-logs?${params.toString()}`);
        if (!cancelled) setPage(result);
      } catch {
        // keep showing the previous page rather than blanking the table on a transient error
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [tenantId, errorType, source, dateFrom, dateTo, offset]);

  function resetAndSet(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      setOffset(0);
      setExpandedId(null);
    };
  }

  return (
    <div className="grid">
      <DataToolbar
        title={t("title")}
        description={t("description")}
      />

      <article className="card">
        <div className="admin-error-filters">
          <label className="field-stack">
            <span className="field-label">{t("tenant")}</span>
            <TenantPicker value={tenantId || null} onChange={(item) => resetAndSet(setTenantId)(item ? item.id : "")} nullLabel={t("all")} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("errorType")}</span>
            <SearchableSelect
              options={filterOptions.error_types}
              getId={(item) => item}
              getLabel={(item) => item}
              value={errorType || null}
              onChange={(item) => resetAndSet(setErrorType)(item ?? "")}
              nullLabel={t("all")}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("source")}</span>
            <SearchableSelect
              options={filterOptions.sources}
              getId={(s) => s}
              getLabel={(s) => SOURCE_LABELS[s] ?? s}
              value={source || null}
              onChange={(s) => resetAndSet(setSource)(s ?? "")}
              nullLabel={t("all")}
            />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("dateFrom")}</span>
            <DateInput value={dateFrom} max={dateTo || undefined} onChange={(value) => resetAndSet(setDateFrom)(value ?? "")} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("dateTo")}</span>
            <DateInput value={dateTo} min={dateFrom || undefined} onChange={(value) => resetAndSet(setDateTo)(value ?? "")} />
          </label>
        </div>
      </article>

      <FilterTabs<"entries" | "grouped">
        options={[
          { value: "entries", label: t("viewEntries") },
          { value: "grouped", label: t("viewGrouped") },
        ]}
        value={view}
        onChange={setView}
      />

      {view === "grouped" ? (
        <DataTable
          columns={[t("colType"), t("colCount"), t("colTenants"), t("colFirst"), t("colLast")]}
          emptyMessage={groups === null ? t("loading") : t("noErrorsFound")}
        >
          {(groups ?? []).map((group) => (
            <tr key={group.error_type}>
              <td>
                {/* Sprung zu den Einträgen dieses Typs */}
                <button
                  type="button"
                  className="table-row-link"
                  onClick={() => {
                    resetAndSet(setErrorType)(group.error_type);
                    setView("entries");
                  }}
                >
                  <Badge variant="danger">{group.error_type}</Badge>
                </button>
              </td>
              <td>{group.count}</td>
              <td className="muted">{group.tenants}</td>
              <td className="muted">{new Date(group.first_at).toLocaleString(locale)}</td>
              <td>{new Date(group.last_at).toLocaleString(locale)}</td>
            </tr>
          ))}
        </DataTable>
      ) : null}

      {view === "entries" ? (
      <>
      <DataTable
        columns={[t("colTime"), t("tenant"), t("source"), t("colType"), t("colStatus"), t("colRoute"), t("colMessage")]}
        emptyMessage={loading ? t("loading") : t("noErrorsFound")}
      >
        {page.items.map((entry) => (
          <ErrorRow key={entry.id} entry={entry} expanded={expandedId === entry.id} onToggle={() => setExpandedId(expandedId === entry.id ? null : entry.id)} />
        ))}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
      </>
      ) : null}
    </div>
  );
}

function ErrorRow({ entry, expanded, onToggle }: { entry: SystemErrorLogEntry; expanded: boolean; onToggle: () => void }) {
  const t = useTranslations("admin.errorLog");
  const locale = useLocale();
  return (
    <>
      <tr className="table-row-clickable" onClick={onToggle} /* a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Zeitstempel) */>
        <td className="muted">
          {/* Tastatur: Aufklappen über den Zeitstempel-Knopf (aria-expanded), Zeile bleibt klickbar */}
          <button type="button" className="table-row-link table-row-toggle" aria-expanded={expanded} onClick={(event) => { event.stopPropagation(); onToggle(); }}>
            {new Date(entry.created_at).toLocaleString(locale)}
          </button>
        </td>
        <td>{entry.tenant_name ?? <span className="muted">—</span>}</td>
        <td>{SOURCE_LABELS[entry.source] ?? entry.source}</td>
        <td>
          <Badge variant="danger">{entry.error_type}</Badge>
        </td>
        <td className="muted">{entry.status_code ?? "—"}</td>
        <td className="muted">
          {entry.request_method ? `${entry.request_method} ` : ""}
          {entry.request_path ?? "—"}
        </td>
        <td>{entry.error_message}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7}>
            <div className="grid admin-error-details">
              {entry.actor_email && (
                <div className="muted">{t("triggeredBy", { email: entry.actor_email })}</div>
              )}
              {entry.traceback && (
                <pre className="admin-error-traceback">{entry.traceback}</pre>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
