"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ColumnPicker, useColumnVisibility, type ColumnDef } from "@/components/admin/column-picker";
import { SecurityExportButton } from "@/components/admin/security/security-export";
import { TenantPicker } from "@/components/admin/tenant-picker";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { describeAuditAction } from "@/lib/audit-labels";
import { useServerTable, type ServerTableConfig } from "@/lib/admin/use-server-table";
import { formatDateTime } from "@/lib/utils/format";
import { AuditLogEntry, AuditLogPage } from "@/types/api";

const PAGE_SIZE = 50;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ACTOR_KINDS = ["admin", "user", "system"] as const;

type AuditFilters = {
  tenant_id: string;
  action: string;
  outcome: string;
  from: string;
  to: string;
  actor_kind: string;
  actor_id: string;
  entity_type: string;
  entity_id: string;
};

// Filter stehen in der URL - nur IDs und Codes (Plan §5.1/§8.3): Mandanten- und Akteur-IDs, Datum,
// Aktions-Präfix (Code), Entitätstyp und -ID. Nie Namen oder E-Mails.
export const AUDIT_TABLE: ServerTableConfig<AuditFilters> = {
  path: "/api/admin/audit-log",
  pageSize: PAGE_SIZE,
  defaults: { tenant_id: "", action: "", outcome: "", from: "", to: "", actor_kind: "", actor_id: "", entity_type: "", entity_id: "" },
  textKey: "action",
  // Aktions-Präfix ist ein Code (z. B. user.login), keine Personendaten
  syncTextToUrl: true,
  validate: {
    tenant_id: (value) => UUID.test(value),
    actor_id: (value) => UUID.test(value),
    outcome: (value) => value === "failure",
    from: (value) => ISO_DATE.test(value),
    to: (value) => ISO_DATE.test(value),
    actor_kind: (value) => (ACTOR_KINDS as readonly string[]).includes(value),
    entity_type: (value) => /^[a-z0-9_.]{1,64}$/.test(value),
    entity_id: (value) => /^\d{1,18}$/.test(value),
    action: (value) => /^[a-z0-9_.]{0,100}$/i.test(value),
  },
};

type FilterOptions = { entity_types: string[]; admins: { id: string; display_name: string }[] };

// /admin/security/audit: Sicherheits- und Änderungsereignisse aller Mandanten (Datenschutz-Audit PRIV-013).
// Die Quelle ist ein gekürzter, gehashter IP-Fingerprint - nie die Adresse selbst.
export function AdminAuditLog({ initialPage }: { initialPage: AuditLogPage }) {
  const t = useTranslations("admin.auditLog");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const table = useServerTable<AuditFilters, AuditLogPage>(AUDIT_TABLE, initialPage);
  const page = table.data ?? initialPage;
  const [expanded, setExpanded] = useState<number | null>(null);
  const [options, setOptions] = useState<FilterOptions>({ entity_types: [], admins: [] });

  useEffect(() => {
    browserApiFetch<FilterOptions>("/api/admin/audit-log/filter-options").then(setOptions).catch(() => undefined);
  }, []);

  const columns: ColumnDef[] = [
    { key: "time", label: t("colTime"), required: true },
    { key: "tenant", label: t("tenant") },
    { key: "action", label: t("colAction"), required: true },
    { key: "actor", label: t("colActor") },
    { key: "entity", label: t("colEntity"), hidden: true },
    { key: "source", label: t("colSource") },
    { key: "outcome", label: t("colOutcome") },
  ];
  const cols = useColumnVisibility("audit-log", columns);
  const shown = columns.filter((column) => cols.isVisible(column.key));
  const f = table.filters;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        <div className="table-toolbar-actions">
          <ColumnPicker columns={columns} isVisible={cols.isVisible} onToggle={cols.toggle} />
          <SecurityExportButton kind="audit_log" />
        </div>
      </div>
      {table.failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      <div className="list-filter-row">
        <FilterTabs<string>
          options={[
            { value: "", label: t("filterAll") },
            { value: "failure", label: t("filterFailures") },
          ]}
          value={f.outcome}
          onChange={(value) => table.setFilter("outcome", value)}
        />
        <SearchInput value={f.action} onChange={(value) => table.setFilter("action", value)} placeholder={t("actionPlaceholder")} />
      </div>
      <div className="admin-filter-grid">
        <label className="field-stack">
          <span className="field-label">{t("tenant")}</span>
          <TenantPicker value={f.tenant_id || null} onChange={(tenant) => table.setFilter("tenant_id", tenant?.id ?? "")} nullLabel={t("allTenants")} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("from")}</span>
          <DateInput value={f.from} max={f.to || undefined} onChange={(value) => table.setFilter("from", value)} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("to")}</span>
          <DateInput value={f.to} min={f.from || undefined} onChange={(value) => table.setFilter("to", value)} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("actorKind")}</span>
          <Select value={f.actor_kind} onChange={(event) => table.setFilters({ actor_kind: event.target.value, actor_id: "" })}>
            <option value="">{t("actorKinds.all")}</option>
            {ACTOR_KINDS.map((kind) => (
              <option key={kind} value={kind}>{t(`actorKinds.${kind}`)}</option>
            ))}
          </Select>
        </label>
        {f.actor_kind === "admin" ? (
          <label className="field-stack">
            <span className="field-label">{t("actorAdmin")}</span>
            <SearchableSelect
              options={options.admins}
              getId={(item) => item.id}
              getLabel={(item) => item.display_name}
              value={f.actor_id || null}
              onChange={(item) => table.setFilter("actor_id", item?.id ?? "")}
              nullLabel={t("actorAdminAll")}
            />
          </label>
        ) : null}
        <label className="field-stack">
          <span className="field-label">{t("entityType")}</span>
          <SearchableSelect
            options={options.entity_types}
            getId={(item) => item}
            getLabel={(item) => item}
            value={f.entity_type || null}
            onChange={(item) => table.setFilters({ entity_type: item ?? "", entity_id: item ? f.entity_id : "" })}
            nullLabel={t("entityTypeAll")}
          />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("entityId")}</span>
          <input
            inputMode="numeric"
            value={f.entity_id}
            disabled={!f.entity_type}
            onChange={(event) => table.setFilter("entity_id", event.target.value.replace(/\D/g, "").slice(0, 18))}
          />
        </label>
      </div>
      {f.actor_kind === "user" && f.actor_id ? <StatusBanner tone="neutral" message={t("actorUserFilter")} /> : null}
      <DataTable columns={shown.map((column) => column.label)} emptyMessage={table.loading ? t("loading") : t("empty")}>
        {page.items.map((entry) => (
          <AuditRow
            key={entry.id}
            entry={entry}
            visible={cols.isVisible}
            colSpan={shown.length}
            label={describeAuditAction(entry.action, tActions)}
            time={formatDateTime(entry.created_at, locale)}
            expanded={expanded === entry.id}
            onToggle={() => setExpanded(expanded === entry.id ? null : entry.id)}
          />
        ))}
      </DataTable>
      <Pagination offset={table.offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={table.setOffset} />
    </div>
  );
}

function detailValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function AuditRow({
  entry, label, time, expanded, onToggle, visible, colSpan,
}: { entry: AuditLogEntry; label: string; time: string; expanded: boolean; onToggle: () => void; visible: (key: string) => boolean; colSpan: number }) {
  const t = useTranslations("admin.auditLog");
  const details = Object.entries(entry.details ?? {});
  return (
    <>
      <tr className="table-row-clickable" onClick={onToggle} /* a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Zeitstempel) */>
        <td className="muted">
          {/* Tastatur: Aufklappen über den Zeitstempel-Knopf (aria-expanded), Zeile bleibt klickbar */}
          <button type="button" className="table-row-link table-row-toggle" aria-expanded={expanded} onClick={(event) => { event.stopPropagation(); onToggle(); }}>
            {time}
          </button>
        </td>
        {visible("tenant") ? <td>{entry.tenant_name ?? <span className="muted">—</span>}</td> : null}
        <td>
          <span>{label}</span>
          <span className="audit-log-code">{entry.action}</span>
        </td>
        {visible("actor") ? <td>{entry.actor_name ?? entry.actor_email ?? <span className="muted">—</span>}</td> : null}
        {visible("entity") ? <td>{entry.entity_type ? <code>{`${entry.entity_type}${entry.entity_id ? ` #${entry.entity_id}` : ""}`}</code> : <span className="muted">—</span>}</td> : null}
        {visible("source") ? <td className="muted">{entry.ip_hash ?? "—"}</td> : null}
        {visible("outcome") ? (
          <td>
            <Badge variant={entry.outcome === "failure" ? "danger" : "neutral"}>{t(`outcome.${entry.outcome}`)}</Badge>
          </td>
        ) : null}
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={colSpan}>
            {/* Schlüssel-Wert-Liste statt rohem JSON (Plan §5.1) */}
            <dl className="audit-log-details-list">
              <div className="audit-log-details-pair">
                <dt>{t("detailEntity")}</dt>
                <dd>{entry.entity_type ? `${entry.entity_type}${entry.entity_id ? ` #${entry.entity_id}` : ""}` : "—"}</dd>
              </div>
              {details.map(([key, value]) => (
                <div key={key} className="audit-log-details-pair">
                  <dt><code>{key}</code></dt>
                  <dd>{detailValue(value)}</dd>
                </div>
              ))}
            </dl>
          </td>
        </tr>
      ) : null}
    </>
  );
}
