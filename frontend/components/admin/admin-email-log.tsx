"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import { NotificationLogEntry, NotificationLogPage } from "@/types/api";

const PAGE_SIZE = 50;

type StatusFilter = "all" | NotificationLogEntry["status"];

const STATUS_BADGE: Record<NotificationLogEntry["status"], "success" | "info" | "danger" | "neutral"> = {
  sent: "success",
  pending: "info",
  failed: "danger",
  skipped: "neutral",
};

/** Versandprotokoll aller E-Mails (GET /api/admin/notifications/log): wer, was, wann, Ergebnis. */
export function AdminEmailLog() {
  const t = useTranslations("admin.emailLog");
  const locale = useLocale();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<NotificationLogPage>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);

  // Suche erst nach einer kurzen Tipp-Pause abschicken
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (status !== "all") params.set("status", status);
    if (query) params.set("search", query);
    browserApiFetch<NotificationLogPage>(`/api/admin/notifications/log?${params.toString()}`)
      .then((result) => {
        if (!cancelled && result) setPage(result);
      })
      .catch(() => {
        // vorherige Seite stehen lassen statt die Tabelle zu leeren
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [status, query, offset]);

  // Arten wie «todo.due_soon»: Punkte würde next-intl als Verschachtelung lesen
  const label = (group: "kinds" | "reasons", key: string) => {
    const path = `${group}.${key.replace(/\./g, "_")}`;
    return t.has(path) ? t(path) : key;
  };

  return (
    <div className="grid">
      <DataToolbar title={t("title")} description={t("description")} />
      <div className="list-filter-row">
        <FilterTabs
          options={[
            { value: "all", label: t("status.all") },
            { value: "sent", label: t("status.sent") },
            { value: "pending", label: t("status.pending") },
            { value: "failed", label: t("status.failed") },
            { value: "skipped", label: t("status.skipped") },
          ]}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setOffset(0);
          }}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        </div>
      </div>
      <DataTable
        columns={[t("colTime"), t("colTenant"), t("colRecipient"), t("colKind"), t("colStatus")]}
        emptyMessage={loading ? t("loading") : t("empty")}
      >
        {page.items.map((entry) => (
          <tr key={entry.id}>
            <td>
              {formatDateTime(entry.sent_at ?? entry.deliver_after, locale)}
              {!entry.sent_at && entry.status === "pending" ? <div className="muted">{t("plannedHint")}</div> : null}
            </td>
            <td>{entry.tenant_name}</td>
            <td>
              <div>{entry.recipient_name}</div>
              {entry.recipient_email ? <div className="muted">{entry.recipient_email}</div> : null}
            </td>
            <td>{label("kinds", entry.kind)}</td>
            <td>
              <Badge variant={STATUS_BADGE[entry.status]}>{t(`status.${entry.status}`)}</Badge>
              {entry.skip_reason ? <div className="muted">{label("reasons", entry.skip_reason)}</div> : null}
              {entry.last_error && entry.status !== "sent" ? <div className="muted">{entry.last_error}</div> : null}
              {entry.attempts > 1 ? <div className="muted">{t("attempts", { count: entry.attempts })}</div> : null}
            </td>
          </tr>
        ))}
      </DataTable>
      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />
    </div>
  );
}
