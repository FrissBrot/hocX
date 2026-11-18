"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { ColumnFilter, ColumnFilterOptions } from "@/components/ui/column-filter";
import { DataTable } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Pagination } from "@/components/ui/pagination";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { AUDIT_CATEGORIES, describeAuditAction, humanizeCode } from "@/lib/audit-labels";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import { ActivityActor, ActivityEntry, ActivityPage } from "@/types/api";

const PAGE_SIZE = 50;
type OutcomeFilter = "" | "success" | "failure";

type Filters = {
  category: string;
  action: string;
  actor: string;
  outcome: OutcomeFilter;
  dateFrom: string;
  dateTo: string;
};

const NO_FILTERS: Filters = { category: "", action: "", actor: "", outcome: "", dateFrom: "", dateTo: "" };

// Mandanten-Einstellungen → Verlauf: Änderungen, Anmeldungen und Zugriffe der Plattform auf Daten
// dieses Vereins (Datenschutz-Audit PRIV-013). Keine IP-Adressen, keine E-Mail-Adressen.
// Bereich oben mit Suche; jede Spalte hat einen eigenen Filter im Kopf (serverseitig, mit Paginierung).
export function ActivityLog({ initialPage }: { initialPage: ActivityPage }) {
  const t = useTranslations("tenantSettings.activity");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const [page, setPage] = useState(initialPage);
  // Auswahllisten kommen nur mit der ersten Seite (with_options) und bleiben beim Blättern stehen
  const [options, setOptions] = useState({ categories: initialPage.categories, actions: initialPage.actions ?? [], actors: initialPage.actors ?? [] });
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
        if (filters.category) params.set("category", filters.category);
        if (filters.action) params.set("action", filters.action);
        if (filters.actor) params.set("actor", filters.actor);
        if (filters.outcome) params.set("outcome", filters.outcome);
        if (filters.dateFrom) params.set("date_from", filters.dateFrom);
        if (filters.dateTo) params.set("date_to", filters.dateTo);
        if (offset > 0) params.set("with_options", "false");
        const result = await browserApiFetch<ActivityPage>(`/api/activity?${params.toString()}`);
        if (cancelled) return;
        setPage(result);
        if (offset === 0) setOptions({ categories: result.categories, actions: result.actions ?? [], actors: result.actors ?? [] });
      } catch {
        // vorherige Seite stehen lassen statt die Tabelle zu leeren
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [filters, offset]);

  function update(patch: Partial<Filters>) {
    setFilters((current) => ({ ...current, ...patch }));
    setOffset(0);
  }

  const categoryLabel = (code: string) =>
    (AUDIT_CATEGORIES as readonly string[]).includes(code) ? tActions(`categories.${code}`) : humanizeCode(code);

  const actorName = (kind: ActivityActor["kind"], name: string | null) => (kind === "user" ? name ?? "" : t(`actor.${kind}`));
  const actorLabel = (entry: ActivityEntry) => actorName(entry.actor_kind, entry.actor_name);

  const categoryOptions = useMemo(
    () => options.categories.map((code) => ({ code, label: categoryLabel(code) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options.categories],
  );
  const actionOptions = useMemo(
    () => options.actions.map((action) => ({ value: action, label: describeAuditAction(action, tActions) })),
    [options.actions, tActions],
  );
  const actorOptions = useMemo(
    () => options.actors.map((actor) => ({ value: actor.key, label: actorName(actor.kind, actor.name) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options.actors],
  );

  const dateActive = Boolean(filters.dateFrom || filters.dateTo);
  const anyActive = Object.values(filters).some(Boolean);
  const actionLabel = actionOptions.find((option) => option.value === filters.action)?.label;
  const actorFilterLabel = actorOptions.find((option) => option.value === filters.actor)?.label;

  const columns = [
    {
      key: "time",
      label: t("colTime"),
      header: (
        <ColumnFilter label={t("colTime")} active={dateActive}>
          {(close) => (
            <div className="column-filter-dates">
              <div className="two-col">
                <label className="field-stack">
                  <span className="field-label">{t("dateFrom")}</span>
                  <DateInput value={filters.dateFrom} max={filters.dateTo || undefined} onChange={(value) => update({ dateFrom: value })} />
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("dateTo")}</span>
                  <DateInput value={filters.dateTo} min={filters.dateFrom || undefined} onChange={(value) => update({ dateTo: value })} />
                </label>
              </div>
              {dateActive ? (
                <button type="button" className="button-ghost" onClick={() => { update({ dateFrom: "", dateTo: "" }); close(); }}>
                  {t("clearFilter")}
                </button>
              ) : null}
            </div>
          )}
        </ColumnFilter>
      ),
    },
    {
      key: "action",
      label: t("colAction"),
      header: (
        <ColumnFilter label={t("colAction")} active={Boolean(filters.action)}>
          {(close) => (
            <ColumnFilterOptions
              options={actionOptions}
              value={filters.action}
              allLabel={t("allActions")}
              onChange={(value) => { update({ action: value }); close(); }}
            />
          )}
        </ColumnFilter>
      ),
    },
    {
      key: "actor",
      label: t("colActor"),
      header: (
        <ColumnFilter label={t("colActor")} active={Boolean(filters.actor)}>
          {(close) => (
            <ColumnFilterOptions
              options={actorOptions}
              value={filters.actor}
              allLabel={t("allActors")}
              onChange={(value) => { update({ actor: value }); close(); }}
            />
          )}
        </ColumnFilter>
      ),
    },
    {
      key: "outcome",
      label: t("colOutcome"),
      header: (
        <ColumnFilter label={t("colOutcome")} active={Boolean(filters.outcome)} align="end">
          {(close) => (
            <ColumnFilterOptions
              searchable={false}
              options={[
                { value: "success", label: t("outcome.success") },
                { value: "failure", label: t("outcome.failure") },
              ]}
              value={filters.outcome}
              allLabel={t("allOutcomes")}
              onChange={(value) => { update({ outcome: value as OutcomeFilter }); close(); }}
            />
          )}
        </ColumnFilter>
      ),
    },
  ];

  // Aktive Filter als Chips über der Tabelle: sichtbar, was eingeschränkt ist, einzeln entfernbar
  const chips: { key: string; label: string; clear: Partial<Filters> }[] = [];
  if (dateActive) {
    const from = filters.dateFrom ? formatDate(filters.dateFrom) : "…";
    const to = filters.dateTo ? formatDate(filters.dateTo) : "…";
    chips.push({ key: "date", label: t("chipDate", { from, to }), clear: { dateFrom: "", dateTo: "" } });
  }
  if (filters.action) chips.push({ key: "action", label: actionLabel ?? filters.action, clear: { action: "" } });
  if (filters.actor) chips.push({ key: "actor", label: actorFilterLabel ?? filters.actor, clear: { actor: "" } });
  if (filters.outcome) chips.push({ key: "outcome", label: t(`outcome.${filters.outcome}`), clear: { outcome: "" } });

  return (
    <div className="grid">
      <p className="muted">{t("intro")}</p>
      <div className="list-filter-row activity-filter-row">
        <label className="field-stack activity-category-field">
          <span className="field-label">{t("category")}</span>
          <SearchableSelect
            options={categoryOptions}
            getId={(option) => option.code}
            getLabel={(option) => option.label}
            value={filters.category || null}
            nullLabel={t("allCategories")}
            placeholder={t("allCategories")}
            onChange={(option) => update({ category: option?.code ?? "", action: "" })}
          />
        </label>
        {chips.length ? (
          <div className="activity-filter-chips">
            {chips.map((chip) => (
              <button key={chip.key} type="button" className="button-pill activity-filter-chip" onClick={() => update(chip.clear)} aria-label={t("removeFilter", { filter: chip.label })}>
                {chip.label} <span aria-hidden="true">×</span>
              </button>
            ))}
            {anyActive ? (
              <button type="button" className="button-ghost" onClick={() => { setFilters(NO_FILTERS); setOffset(0); }}>
                {t("clearAll")}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <DataTable columns={columns} emptyMessage={loading ? t("loading") : anyActive ? t("emptyFiltered") : t("empty")}>
        {page.items.map((entry, index) => (
          <tr key={`${entry.created_at}-${index}`}>
            <td className="muted">{formatDateTime(entry.created_at, locale)}</td>
            <td>{describeAuditAction(entry.action, tActions)}</td>
            <td>{actorLabel(entry)}</td>
            <td>
              <Badge variant={entry.outcome === "failure" ? "danger" : "neutral"}>{t(`outcome.${entry.outcome}`)}</Badge>
            </td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </div>
  );
}
