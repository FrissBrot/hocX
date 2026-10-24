"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { describeAuditAction } from "@/lib/audit-labels";
import { formatDateTime } from "@/lib/utils/format";
import { AdminTenantSummary, AuditLogEntry, AuditLogPage } from "@/types/api";

const PAGE_SIZE = 50;
type OutcomeFilter = "all" | "failure";

// /admin/audit: Sicherheits- und Änderungsereignisse aller Mandanten (Datenschutz-Audit PRIV-013).
// Die Quelle ist ein gekürzter, gehashter IP-Fingerprint - nie die Adresse selbst.
export function AdminAuditLog({ initialPage, tenants }: { initialPage: AuditLogPage; tenants: AdminTenantSummary[] }) {
  const t = useTranslations("admin.auditLog");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const [page, setPage] = useState(initialPage);
  const [tenantId, setTenantId] = useState("");
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState<OutcomeFilter>("all");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
        if (tenantId) params.set("tenant_id", tenantId);
        if (action.trim()) params.set("action", action.trim());
        if (outcome === "failure") params.set("outcome", "failure");
        const result = await browserApiFetch<AuditLogPage>(`/api/admin/audit-log?${params.toString()}`);
        if (!cancelled) setPage(result);
      } catch {
        // vorherige Seite stehen lassen
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [tenantId, action, outcome, offset]);

  return (
    <div className="grid">
      <DataToolbar title={t("title")} description={t("description")} />
      <div className="list-filter-row">
        <FilterTabs<OutcomeFilter>
          options={[
            { value: "all", label: t("filterAll") },
            { value: "failure", label: t("filterFailures") },
          ]}
          value={outcome}
          onChange={(value) => {
            setOutcome(value);
            setOffset(0);
          }}
        />
        <label className="field-stack">
          <span className="field-label">{t("tenant")}</span>
          <SearchableSelect
            options={tenants}
            getId={(item) => String(item.id)}
            getLabel={(item) => item.name}
            value={tenantId || null}
            onChange={(item) => {
              setTenantId(item ? String(item.id) : "");
              setOffset(0);
            }}
            nullLabel={t("allTenants")}
          />
        </label>
        <SearchInput
          value={action}
          onChange={(value) => {
            setAction(value);
            setOffset(0);
          }}
          placeholder={t("actionPlaceholder")}
        />
      </div>
      <DataTable
        columns={[t("colTime"), t("tenant"), t("colAction"), t("colActor"), t("colSource"), t("colOutcome")]}
        emptyMessage={loading ? t("loading") : t("empty")}
      >
        {page.items.map((entry) => (
          <AuditRow
            key={entry.id}
            entry={entry}
            label={describeAuditAction(entry.action, tActions)}
            time={formatDateTime(entry.created_at, locale)}
            expanded={expanded === entry.id}
            onToggle={() => setExpanded(expanded === entry.id ? null : entry.id)}
          />
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </div>
  );
}

function AuditRow({ entry, label, time, expanded, onToggle }: { entry: AuditLogEntry; label: string; time: string; expanded: boolean; onToggle: () => void }) {
  const t = useTranslations("admin.auditLog");
  return (
    <>
      <tr className="table-row-clickable" onClick={onToggle}>
        <td className="muted">{time}</td>
        <td>{entry.tenant_name ?? <span className="muted">—</span>}</td>
        <td>
          <span>{label}</span>
          <span className="audit-log-code">{entry.action}</span>
        </td>
        <td>{entry.actor_name ?? entry.actor_email ?? <span className="muted">—</span>}</td>
        <td className="muted">{entry.ip_hash ?? "—"}</td>
        <td>
          <Badge variant={entry.outcome === "failure" ? "danger" : "neutral"}>{t(`outcome.${entry.outcome}`)}</Badge>
        </td>
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={6}>
            <pre className="audit-log-details">{JSON.stringify({ entity: entry.entity_type, id: entry.entity_id, ...entry.details }, null, 2)}</pre>
          </td>
        </tr>
      ) : null}
    </>
  );
}
