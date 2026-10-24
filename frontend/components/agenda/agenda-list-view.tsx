"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { AgendaItemModal, AgendaPostponeModal } from "@/components/agenda/agenda-item-modal";
import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatMonthYear } from "@/lib/utils/format";
import { AgendaItem, AgendaTemplateOption } from "@/types/api";

type Filter = "open" | "treated" | "all";

type Props = {
  items: AgendaItem[];
  templates: AgendaTemplateOption[];
  preferredTemplateId: string | null;
  canEdit: boolean;
};

export function AgendaListView({ items: initialItems, templates, preferredTemplateId, canEdit }: Props) {
  const t = useTranslations("agenda");
  const locale = useLocale();
  const router = useRouter();
  const showToast = useToast();
  const confirm = useConfirm();
  const [items, setItems] = useState(initialItems);
  const [filter, setFilter] = useState<Filter>("open");
  const [search, setSearch] = useState("");
  const [preference, setPreference] = useState(preferredTemplateId);
  const [creating, setCreating] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [postponeId, setPostponeId] = useState<string | null>(null);

  const counts = useMemo(
    () => ({
      open: items.filter((item) => item.state !== "treated").length,
      treated: items.filter((item) => item.state === "treated").length,
    }),
    [items]
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return items.filter((item) => {
      if (filter === "open" && item.state === "treated") return false;
      if (filter === "treated" && item.state !== "treated") return false;
      if (!query) return true;
      return [item.title, item.body ?? "", item.template_name, item.template_element_name ?? "", item.created_by_name ?? ""]
        .some((value) => value.toLowerCase().includes(query));
    });
  }, [items, filter, search]);

  function upsert(saved: AgendaItem) {
    setItems((current) => (current.some((item) => item.id === saved.id)
      ? current.map((item) => (item.id === saved.id ? saved : item))
      : [saved, ...current]));
  }

  async function remove(item: AgendaItem) {
    const ok = await confirm({ message: t("deleteConfirm", { title: item.title }), tone: "danger", confirmLabel: t("actionDelete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/agenda-items/${item.id}`, { method: "DELETE" });
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      showToast(t("deleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorDelete"), "error");
    }
  }

  function scheduleLabel(item: AgendaItem) {
    if (item.protocol) {
      const values = { number: item.protocol.protocol_number, date: formatDate(item.protocol.protocol_date) ?? "" };
      return item.state === "treated" ? t("stateTreated", values) : t("stateScheduled", values);
    }
    return item.schedule_kind === "month" && item.scheduled_month
      ? t("scheduleFromMonth", { month: formatMonthYear(item.scheduled_month, locale) })
      : t("scheduleNextMeeting");
  }

  function scheduleHint(item: AgendaItem) {
    if (!item.protocol) return t("stateWaiting");
    if (item.is_bound) return null;
    return item.schedule_kind === "month" && item.scheduled_month
      ? t("scheduleFromMonth", { month: formatMonthYear(item.scheduled_month, locale) })
      : t("scheduleNextMeeting");
  }

  function menuItems(item: AgendaItem): ActionMenuItem[] {
    const entries: ActionMenuItem[] = [];
    if (canEdit && item.can_edit) {
      entries.push({ label: t("actionEdit"), onClick: () => setEditId(item.id) });
      entries.push({ label: t("actionPostpone"), onClick: () => setPostponeId(item.id) });
    }
    if (item.protocol) entries.push({ label: t("actionOpenProtocol"), onClick: () => router.push(`/protocols/${item.protocol!.id}`) });
    if (canEdit && item.can_edit) entries.push({ label: t("actionDelete"), onClick: () => void remove(item), danger: true });
    return entries;
  }

  const editing = items.find((item) => item.id === editId) ?? null;
  const postponing = items.find((item) => item.id === postponeId) ?? null;
  const showEmptyState = items.length === 0 || (filter === "open" && counts.open === 0 && !search);

  return (
    <div className="grid agenda-overview">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageIntro")}</p>
        </div>
        {canEdit && !showEmptyState && (
          <button type="button" className="button-secondary" onClick={() => setCreating(true)}>
            {t("addButton")}
          </button>
        )}
      </div>

      {items.length > 0 && (
        <div className="list-filter-row">
          <FilterTabs
            options={[
              { value: "open", label: t("filterOpen"), count: counts.open || undefined },
              { value: "treated", label: t("filterTreated"), count: counts.treated || undefined },
              { value: "all", label: t("filterAll") },
            ]}
            value={filter}
            onChange={setFilter}
          />
          <div className="list-filter-search">
            <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
          </div>
        </div>
      )}

      {showEmptyState ? (
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          actions={
            <>
              {canEdit ? (
                <button type="button" className="button-primary" onClick={() => setCreating(true)}>
                  {t("addButton")}
                </button>
              ) : null}
              {counts.treated > 0 ? (
                <button type="button" className="button-secondary" onClick={() => setFilter("treated")}>
                  {t("filterTreated")}
                </button>
              ) : null}
            </>
          }
        />
      ) : (
        <DataTable
          className="data-table-lg data-table-agenda"
          columns={[
            { key: "title", label: t("colTitle") },
            { key: "place", label: t("colPlace") },
            { key: "schedule", label: t("colSchedule") },
            { key: "created_by", label: t("colCreatedBy") },
            { key: "actions", label: "", header: <span aria-label={t("colActions")} /> },
          ]}
          emptyMessage={t("noResults")}
        >
          {filtered.map((item) => {
            const hint = scheduleHint(item);
            const actions = menuItems(item);
            return (
              <tr
                key={item.id}
                className={`${item.state === "treated" ? "table-row-done" : ""}${canEdit ? " table-row-clickable" : ""}`}
                onClick={() => canEdit && setEditId(item.id)}
              >
                <td>
                  <div className="agenda-row-title">
                    <span className="agenda-row-title-text">{item.title}</span>
                    {item.postponed_count > 0 && <Badge variant="warning">{t("postponedBadge", { count: item.postponed_count })}</Badge>}
                  </div>
                  {item.body ? <div className="agenda-row-body muted">{item.body.replace(/[*_#>`~-]/g, "").slice(0, 160)}</div> : null}
                </td>
                <td>
                  <div>{item.template_name}</div>
                  <div className="muted">{item.template_element_name ?? t("noPoint")}</div>
                </td>
                <td>
                  <div>{scheduleLabel(item)}</div>
                  {hint ? <div className="muted">{hint}</div> : null}
                </td>
                <td>
                  <span className={item.created_by_name ? "" : "muted"}>{item.created_by_name ?? "—"}</span>
                </td>
                <td className="agenda-row-actions">{actions.length > 0 ? <ActionMenu items={actions} /> : null}</td>
              </tr>
            );
          })}
        </DataTable>
      )}

      {creating && (
        <AgendaItemModal
          templates={templates}
          preferredTemplateId={preference}
          canEdit={canEdit}
          onClose={() => setCreating(false)}
          onSaved={upsert}
          onTemplateRemembered={setPreference}
        />
      )}
      {editing && (
        <AgendaItemModal
          key={editing.id}
          item={editing}
          templates={templates}
          canEdit={canEdit}
          onClose={() => setEditId(null)}
          onSaved={upsert}
        />
      )}
      {postponing && <AgendaPostponeModal item={postponing} onClose={() => setPostponeId(null)} onPostponed={upsert} />}
    </div>
  );
}
