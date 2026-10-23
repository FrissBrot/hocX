"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { browserApiFetch } from "@/lib/api/client";
import { AUDIT_CATEGORIES, describeAuditAction, humanizeCode } from "@/lib/audit-labels";
import { formatDateTime } from "@/lib/utils/format";
import { ActivityEntry, ActivityPage } from "@/types/api";

const PAGE_SIZE = 50;
type OutcomeFilter = "all" | "failure";

// Mandanten-Einstellungen → Verlauf: Änderungen, Anmeldungen und Zugriffe der Plattform auf Daten
// dieses Vereins (Datenschutz-Audit PRIV-013). Keine IP-Adressen, keine E-Mail-Adressen.
export function ActivityLog({ initialPage }: { initialPage: ActivityPage }) {
  const t = useTranslations("tenantSettings.activity");
  const tActions = useTranslations("common.auditActions");
  const locale = useLocale();
  const [page, setPage] = useState(initialPage);
  const [category, setCategory] = useState("");
  const [outcome, setOutcome] = useState<OutcomeFilter>("all");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
        if (category) params.set("category", category);
        if (outcome === "failure") params.set("outcome", "failure");
        const result = await browserApiFetch<ActivityPage>(`/api/activity?${params.toString()}`);
        if (!cancelled) setPage(result);
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
  }, [category, outcome, offset]);

  const categoryLabel = (code: string) =>
    (AUDIT_CATEGORIES as readonly string[]).includes(code) ? tActions(`categories.${code}`) : humanizeCode(code);

  const actorLabel = (entry: ActivityEntry) => {
    if (entry.actor_kind === "user") return entry.actor_name ?? "";
    return t(`actor.${entry.actor_kind}`);
  };

  return (
    <div className="grid">
      <p className="muted">{t("intro")}</p>
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
          <span className="field-label">{t("category")}</span>
          <select
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">{t("allCategories")}</option>
            {page.categories.map((code) => (
              <option key={code} value={code}>
                {categoryLabel(code)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <DataTable columns={[t("colTime"), t("colAction"), t("colActor"), t("colOutcome")]} emptyMessage={loading ? t("loading") : t("empty")}>
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
