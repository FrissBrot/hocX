"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession, useOpenMore } from "@/components/mobile/mobile-shell";
import {
  MobileActionSheet,
  MobileAvatar,
  MobileDesktopHint,
  MobileEmpty,
  MobileFab,
  MobileListRow,
  MobileSubHeader,
  MobileSwitch,
} from "@/components/mobile/mobile-ui";
import { dateParts } from "@/components/mobile/mobile-utils";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { EventSummary, ParticipantSummary, StructuredListDefinition, StructuredListEntry, StructuredListValueType } from "@/types/api";
import { Select } from "@/components/ui/select";
import { ColumnFormState, columnsForForm, createListDefinition, isPersonType, ListSaveRequest, MAX_COLUMNS, newLocalId, updateListDefinition } from "@/lib/lists/save-list";

type Value = Record<string, unknown>;
const VALUE_TYPES: StructuredListValueType[] = ["text", "participant", "participants", "event"];

function orderedColumns(list: StructuredListDefinition) {
  return [...list.columns].sort((left, right) => left.sort_index - right.sort_index);
}

/** Spalte, die einen Eintrag benennt (Rolle «Bezeichnung», sonst die erste Spalte). */
function labelColumnOf(list: StructuredListDefinition) {
  const columns = orderedColumns(list);
  return columns.find((column) => column.id === list.label_column_id) ?? columns[0];
}

function emptyValue(type: StructuredListValueType): Value {
  if (type === "participant") return { participant_id: null };
  if (type === "participants") return { participant_ids: [] };
  if (type === "event") return { event_id: null };
  return { text_value: "" };
}

function useValueLabel(participants: ParticipantSummary[], events: EventSummary[]) {
  const locale = useLocale();
  return (type: StructuredListValueType, value: Value): string => {
    if (type === "participant") return participants.find((item) => item.id === value.participant_id)?.display_name ?? "";
    if (type === "participants") {
      const ids = Array.isArray(value.participant_ids) ? (value.participant_ids as string[]) : [];
      return ids.map((id) => participants.find((item) => item.id === id)?.display_name).filter(Boolean).join(", ");
    }
    if (type === "event") {
      const event = events.find((item) => item.id === value.event_id);
      return event ? `${event.title} · ${dateParts.dayMonth(event.event_date, locale)}` : "";
    }
    return String(value.text_value ?? "");
  };
}

export function MobileLists({
  initialLists,
  initialEntriesByList,
  participants,
  events,
}: {
  initialLists: StructuredListDefinition[];
  initialEntriesByList: Record<string, StructuredListEntry[]>;
  participants: ParticipantSummary[];
  events: EventSummary[];
}) {
  const t = useTranslations("lists");
  const tMobile = useTranslations("mobile");
  const openMore = useOpenMore();
  const session = useMobileSession();
  const confirm = useConfirm();
  const showToast = useToast();
  const valueLabel = useValueLabel(participants, events);
  const [lists, setLists] = useState(initialLists);
  const [entries, setEntries] = useState(initialEntriesByList);
  const [search, setSearch] = useState("");
  const [openListId, setOpenListId] = useState<string | null>(null);
  const [listForm, setListForm] = useState<StructuredListDefinition | "new" | null>(null);
  const [entryForm, setEntryForm] = useState<StructuredListEntry | "new" | null>(null);
  const [listActions, setListActions] = useState(false);
  const [entrySearch, setEntrySearch] = useState("");
  const openList = lists.find((list) => list.id === openListId) ?? null;

  const visibleLists = lists.filter((list) => !search.trim() || list.name.toLowerCase().includes(search.trim().toLowerCase()));
  const listEntries = useMemo(() => {
    if (!openList) return [];
    const needle = entrySearch.trim().toLowerCase();
    return [...(entries[openList.id] ?? [])]
      .sort((a, b) => a.sort_index - b.sort_index)
      .filter(
        (entry) =>
          !needle ||
          orderedColumns(openList).map((column) => valueLabel(column.value_type, entry.values?.[column.id] ?? {})).join(" ").toLowerCase().includes(needle)
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openList, entries, entrySearch]);

  async function deleteList(list: StructuredListDefinition) {
    if (!(await confirm({ message: t("toasts.deleteListConfirm"), tone: "danger", confirmLabel: t("toasts.deleteLabel") }))) return;
    try {
      await browserApiFetch(`/api/lists/${list.id}`, { method: "DELETE" });
      setLists((current) => current.filter((item) => item.id !== list.id));
      setOpenListId(null);
      showToast(t("toasts.listDeleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.listDeleteFailed"), "error");
    }
  }

  if (openList) {
    return (
      <div className="mobile-page mobile-page-list">
        <MobileSubHeader
          title={openList.name}
          subtitle={orderedColumns(openList).map((column) => column.title).join(" · ")}
          backLabel={t("pageTitle")}
          onBack={() => setOpenListId(null)}
          actions={
            <button type="button" className="mobile-icon-button" aria-label={t("table.actionsLabel")} onClick={() => setListActions(true)}>
              <MobileIcon name="more" />
            </button>
          }
        />
        <div className="mobile-section">
          <SearchInput value={entrySearch} onChange={setEntrySearch} placeholder={tMobile("common.searchPlaceholder")} />
        </div>
        {listEntries.length > 0 ? (
          <div className="mobile-section">
            <div className="mobile-card mobile-list-card">
              {listEntries.map((entry) => {
                // Karte: Bezeichnungs-Spalte als Titel, die übrigen Spalten darunter (Plan 6.2)
                const titleColumn = labelColumnOf(openList);
                const first = titleColumn ? valueLabel(titleColumn.value_type, entry.values?.[titleColumn.id] ?? {}) : "";
                const rest = orderedColumns(openList)
                  .filter((column) => column.id !== titleColumn?.id)
                  .map((column) => valueLabel(column.value_type, entry.values?.[column.id] ?? {}))
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <MobileListRow
                    key={entry.id}
                    onClick={() => setEntryForm(entry)}
                    leading={titleColumn?.value_type === "participant" && first ? <MobileAvatar name={first} size="sm" /> : undefined}
                    label={
                      <span className="mobile-row-stack">
                        <span className="mobile-row-title">{first || t("table.noValue")}</span>
                        <span className="mobile-row-meta">{rest || t("table.noValue")}</span>
                      </span>
                    }
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <MobileEmpty title={t("table.emptyMessage")} />
        )}
        <div className="mobile-section">
          <MobileDesktopHint text={tMobile("lists.historyHint")} email={session?.user?.email} />
        </div>
        <MobileFab label={tMobile("lists.entryFab")} onClick={() => setEntryForm("new")} />

        {listActions ? (
          <MobileActionSheet
            title={openList.name}
            onClose={() => setListActions(false)}
            actions={[
              { label: t("edit"), onClick: () => setListForm(openList) },
              { label: t("deleteList"), onClick: () => void deleteList(openList), danger: true },
            ]}
          />
        ) : null}
        {listForm ? <ListFormSheet list={listForm === "new" ? null : listForm} onClose={() => setListForm(null)} onSaved={(saved) => {
          setLists((current) => current.map((item) => (item.id === saved.id ? saved : item)));
          setListForm(null);
        }} /> : null}
        {entryForm ? (
          <EntrySheet
            list={openList}
            entry={entryForm === "new" ? null : entryForm}
            participants={participants}
            events={events}
            nextSortIndex={(entries[openList.id] ?? []).reduce((max, entry) => Math.max(max, entry.sort_index), -1) + 1}
            onClose={() => setEntryForm(null)}
            onSaved={(saved, created) => {
              setEntries((current) => ({
                ...current,
                [openList.id]: created ? [...(current[openList.id] ?? []), saved] : (current[openList.id] ?? []).map((item) => (item.id === saved.id ? saved : item)),
              }));
              setEntryForm(null);
            }}
            onDeleted={(id) => {
              setEntries((current) => ({ ...current, [openList.id]: (current[openList.id] ?? []).filter((item) => item.id !== id) }));
              setEntryForm(null);
            }}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("pageTitle")} subtitle={t("pageDescriptionEmpty")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <SearchInput value={search} onChange={setSearch} placeholder={t("sidebar.searchPlaceholder")} />
      </div>
      {visibleLists.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visibleLists.map((list) => (
              <MobileListRow
                key={list.id}
                onClick={() => {
                  setOpenListId(list.id);
                  setEntrySearch("");
                }}
                label={
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{list.name}</span>
                    <span className="mobile-row-meta">
                      {t("columns.count", { count: list.columns.length })} · {t("sidebar.entryCount", { count: (entries[list.id] ?? []).length })}
                    </span>
                  </span>
                }
                trailing={<span className={list.is_active ? "mobile-cycle-pill" : "mobile-status-pill"}>{list.is_active ? t("formModal.active") : tMobile("lists.inactive")}</span>}
              />
            ))}
          </div>
        </div>
      ) : (
        <MobileEmpty title={lists.length ? t("sidebar.empty") : t("emptyState.title")} hint={lists.length ? undefined : t("emptyState.description")} />
      )}
      <MobileFab label={tMobile("lists.fab")} onClick={() => setListForm("new")} />
      {listForm ? (
        <ListFormSheet
          list={listForm === "new" ? null : listForm}
          onClose={() => setListForm(null)}
          onSaved={(saved, created) => {
            setLists((current) => (created ? [saved, ...current] : current.map((item) => (item.id === saved.id ? saved : item))));
            setEntries((current) => ({ ...current, [saved.id]: current[saved.id] ?? [] }));
            setListForm(null);
            if (created) setOpenListId(saved.id);
          }}
        />
      ) : null}
    </div>
  );
}

function ListFormSheet({ list, onClose, onSaved }: { list: StructuredListDefinition | null; onClose: () => void; onSaved: (list: StructuredListDefinition, created: boolean) => void }) {
  const t = useTranslations("lists");
  const showToast = useToast();
  const confirm = useConfirm();
  const [form, setForm] = useState(() => ({
    name: list?.name ?? "",
    description: list?.description ?? "",
    is_active: list?.is_active ?? true,
    columns: list
      ? columnsForForm(list)
      : [
          { localId: newLocalId(), title: t("defaultColumnOne"), value_type: "participant" as StructuredListValueType },
          { localId: newLocalId(), title: t("defaultColumnTwo"), value_type: "text" as StructuredListValueType },
        ],
  }));
  const [saving, setSaving] = useState(false);
  const update = (patch: Partial<typeof form>) => setForm((current) => ({ ...current, ...patch }));
  const updateColumn = (localId: string, patch: Partial<ColumnFormState>) =>
    setForm((current) => ({ ...current, columns: current.columns.map((column) => (column.localId === localId ? { ...column, ...patch } : column)) }));
  const valid = form.name.trim() && form.columns.length > 0 && form.columns.every((column) => column.title.trim());

  async function save() {
    if (!valid || saving) return;
    setSaving(true);
    // Rollen: bestehende behalten (auf dem Handy ohne eigene Auswahl), neue Listen wie am Desktop
    const keep = (key: string | null | undefined, personRole: boolean) =>
      form.columns.find((column) => column.id === key && isPersonType(column.value_type) === personRole)?.localId
      ?? form.columns.find((column) => isPersonType(column.value_type) === personRole)?.localId ?? "";
    const request: ListSaveRequest = {
      name: form.name,
      description: form.description,
      is_active: form.is_active,
      is_group_source: list?.is_group_source ?? false,
      columns: form.columns,
      labelColumn: keep(list?.label_column_id, false),
      responsibleColumn: keep(list?.responsible_column_id, true),
    };
    try {
      const saved = list
        ? await updateListDefinition(list, request, {
            confirmRemove: (column, usages) => confirm({
              message: usages.length
                ? t("columns.deleteConfirmUsed", { title: column.title, places: usages.map((usage) => usage.label).join(", ") })
                : t("columns.deleteConfirm", { title: column.title }),
              tone: "danger",
              confirmLabel: t("columns.deleteLabel"),
            }),
            confirmRetype: (titles) => confirm({ message: t("columns.typeChangeConfirm", { titles: titles.join(", ") }), tone: "danger", confirmLabel: t("columns.typeChangeLabel") }),
          })
        : await createListDefinition(request);
      if (!saved) return;
      showToast(list ? t("toasts.listSaved") : t("toasts.listCreated"), "success");
      onSaved(saved, !list);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.listSaveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={list ? t("formModal.editTitle") : t("formModal.createTitle")}
      description={t("formModal.description")}
      onClose={onClose}
      className="mobile-sheet mobile-sheet-tall"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-primary" data-modal-save disabled={!valid || saving} onClick={() => void save()}>
            {list ? t("formModal.save") : t("formModal.create")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("formModal.name")}</span>
          <input value={form.name} onChange={(event) => update({ name: event.target.value })} />
        </label>
        <div className="mobile-card mobile-group-card">
          <button type="button" className="mobile-list-row" aria-pressed={form.is_active} onClick={() => update({ is_active: !form.is_active })}>
            <span className="mobile-list-row-label">{t("formModal.active")}</span>
            <MobileSwitch checked={form.is_active} />
          </button>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("formModal.description2")}</span>
          <input value={form.description} placeholder={t("formModal.descriptionPlaceholder")} onChange={(event) => update({ description: event.target.value })} />
        </label>
        <span className="field-label">{t("formModal.columns")}</span>
        {form.columns.map((column, index) => (
          <div key={column.localId} className="mobile-list-column-row">
            <input aria-label={t("columns.titleLabel", { number: index + 1 })} value={column.title} onChange={(event) => updateColumn(column.localId, { title: event.target.value })} />
            <Select aria-label={t("columns.typeLabel", { number: index + 1 })} value={column.value_type} onChange={(event) => updateColumn(column.localId, { value_type: event.target.value as StructuredListValueType })}>
              {VALUE_TYPES.map((type) => <option key={type} value={type}>{t(`valueTypes.${type}`)}</option>)}
            </Select>
            <button
              type="button"
              className="mobile-icon-button"
              aria-label={t("columns.remove", { title: column.title })}
              disabled={form.columns.length <= 1}
              onClick={() => update({ columns: form.columns.filter((entry) => entry.localId !== column.localId) })}
            >
              <MobileIcon name="trash" />
            </button>
          </div>
        ))}
        {form.columns.length < MAX_COLUMNS ? (
          <button
            type="button"
            className="button-secondary"
            onClick={() => update({ columns: [...form.columns, { localId: newLocalId(), title: t("columns.newTitle", { number: form.columns.length + 1 }), value_type: "text" }] })}
          >
            {t("columns.add")}
          </button>
        ) : null}
      </div>
    </Modal>
  );
}

function ValueField({
  type,
  value,
  onChange,
  participants,
  events,
}: {
  type: StructuredListValueType;
  value: Value;
  onChange: (value: Value) => void;
  participants: ParticipantSummary[];
  events: EventSummary[];
}) {
  const t = useTranslations("lists");
  const locale = useLocale();
  if (type === "participant") {
    return (
      <SearchableSelect
        options={participants}
        getId={(item) => item.id}
        getLabel={(item) => item.display_name}
        value={(value.participant_id as string | null) ?? null}
        onChange={(option) => onChange({ participant_id: option?.id ?? null })}
        nullLabel={t("table.noValue")}
      />
    );
  }
  if (type === "participants") {
    const ids = Array.isArray(value.participant_ids) ? (value.participant_ids as string[]) : [];
    return (
      <div className="mobile-card mobile-group-card mobile-scroll-list">
        {participants.filter((participant) => participant.is_active || ids.includes(participant.id)).map((participant) => {
          const on = ids.includes(participant.id);
          return (
            <button
              key={participant.id}
              type="button"
              className="mobile-list-row"
              aria-pressed={on}
              onClick={() => onChange({ participant_ids: on ? ids.filter((id) => id !== participant.id) : [...ids, participant.id] })}
            >
              <span className={`mobile-check mobile-check-square${on ? " mobile-check-on" : ""}`} aria-hidden="true">
                {on ? <MobileIcon name="check" size={14} strokeWidth={3} /> : null}
              </span>
              <span className="mobile-list-row-label">{participant.display_name}</span>
            </button>
          );
        })}
      </div>
    );
  }
  if (type === "event") {
    return (
      <SearchableSelect
        options={events}
        getId={(item) => item.id}
        getLabel={(item) => `${item.title} · ${dateParts.dayMonth(item.event_date, locale)}`}
        value={(value.event_id as string | null) ?? null}
        onChange={(option) => onChange({ event_id: option?.id ?? null })}
        nullLabel={t("table.noValue")}
      />
    );
  }
  return <input value={String(value.text_value ?? "")} onChange={(event) => onChange({ text_value: event.target.value })} />;
}

function EntrySheet({
  list,
  entry,
  participants,
  events,
  nextSortIndex,
  onClose,
  onSaved,
  onDeleted,
}: {
  list: StructuredListDefinition;
  entry: StructuredListEntry | null;
  participants: ParticipantSummary[];
  events: EventSummary[];
  nextSortIndex: number;
  onClose: () => void;
  onSaved: (entry: StructuredListEntry, created: boolean) => void;
  onDeleted: (id: string) => void;
}) {
  const t = useTranslations("lists");
  const tMobile = useTranslations("mobile");
  const confirm = useConfirm();
  const showToast = useToast();
  const [values, setValues] = useState<Record<string, Value>>(() =>
    Object.fromEntries(orderedColumns(list).map((column) => [column.id, entry?.values?.[column.id] ?? emptyValue(column.value_type)]))
  );
  const [saving, setSaving] = useState(false);

  async function save() {
    if (saving) return;
    setSaving(true);
    try {
      const saved = entry
        ? await browserApiFetch<StructuredListEntry>(`/api/list-entries/${entry.id}`, { method: "PATCH", body: JSON.stringify({ values }) })
        : await browserApiFetch<StructuredListEntry>(`/api/lists/${list.id}/entries`, {
            method: "POST",
            body: JSON.stringify({ sort_index: nextSortIndex, values }),
          });
      showToast(entry ? t("toasts.entrySaved") : t("toasts.entryCreated"), "success");
      onSaved(saved, !entry);
    } catch (error) {
      showToast(error instanceof Error ? error.message : entry ? t("toasts.entrySaveFailed") : t("toasts.entryCreateFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!entry || !(await confirm({ message: t("toasts.deleteEntryConfirm"), tone: "danger", confirmLabel: t("toasts.deleteLabel") }))) return;
    try {
      await browserApiFetch(`/api/list-entries/${entry.id}`, { method: "DELETE" });
      showToast(t("toasts.entryDeleted"), "success");
      onDeleted(entry.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.entryDeleteFailed"), "error");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={entry ? tMobile("lists.editEntry") : t("table.newEntryButton")}
      description={list.name}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          {entry ? (
            <button type="button" className="button-danger" onClick={() => void remove()}>
              {t("table.deleteButton")}
            </button>
          ) : (
            <button type="button" className="button-ghost" onClick={onClose}>
              {tMobile("common.cancel")}
            </button>
          )}
          <button type="button" className="button-primary" data-modal-save disabled={saving} onClick={() => void save()}>
            {tMobile("common.save")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        {orderedColumns(list).map((column) => (
          <div className="field-stack" key={column.id}>
            <span className="field-label">{column.title}</span>
            <ValueField
              type={column.value_type}
              value={values[column.id] ?? emptyValue(column.value_type)}
              onChange={(next) => setValues((current) => ({ ...current, [column.id]: next }))}
              participants={participants}
              events={events}
            />
          </div>
        ))}
      </div>
    </Modal>
  );
}
