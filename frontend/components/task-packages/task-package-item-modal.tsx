"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { SearchableMultiSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { eligibleResponsibleList } from "@/lib/utils/responsible-lists";
import {
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  TaskPackageDueRule,
  TaskPackageDueRuleType,
  TaskPackageItem,
  TaskPackageRecurrence,
  TaskPackageRecurrenceType,
  TaskPackageResponsible,
} from "@/types/api";
import { ResponsibleContext, entryLabel, responsibleLabel } from "@/components/task-packages/task-package-labels";

export type TaskPackageItemPayload = {
  task: string;
  reference_link: string | null;
  tags: string[];
  responsible: TaskPackageResponsible[];
  recurrence: TaskPackageRecurrence;
  due_rule: TaskPackageDueRule;
};

type FormState = {
  task: string;
  referenceLink: string;
  tags: string;
  responsible: TaskPackageResponsible[];
  recurrenceType: TaskPackageRecurrenceType;
  dayOfMonth: string;
  weekday: string;
  eventTag: string;
  dueType: TaskPackageDueRuleType;
  dueDay: string;
  dueMonth: string;
  offsetDays: string;
  offsetDirection: "after" | "before";
};

const RECURRENCE_TYPES: TaskPackageRecurrenceType[] = ["once", "monthly", "weekly", "events"];
const DUE_TYPES: TaskPackageDueRuleType[] = ["none", "fixed", "offset"];
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];
const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

type EntryOption = { key: string; listId: string; entryId: string; label: string };

function entryKey(listId: string, entryId: string) {
  return `${listId}:${entryId}`;
}

function formFromItem(item: TaskPackageItem | null): FormState {
  const offset = item?.due_rule.offset_days ?? 0;
  return {
    task: item?.task ?? "",
    referenceLink: item?.reference_link ?? "",
    tags: (item?.tags ?? []).join(", "),
    responsible: item?.responsible ?? [],
    recurrenceType: item?.recurrence.type ?? "once",
    dayOfMonth: String(item?.recurrence.day_of_month ?? 1),
    weekday: String(item?.recurrence.weekday ?? 0),
    eventTag: item?.recurrence.event_tag ?? "",
    dueType: item?.due_rule.type ?? "none",
    dueDay: String(item?.due_rule.day ?? 1),
    dueMonth: String(item?.due_rule.month ?? 1),
    offsetDays: String(Math.abs(offset)),
    offsetDirection: offset < 0 ? "before" : "after",
  };
}

function payloadFromForm(form: FormState): TaskPackageItemPayload {
  const recurrence: TaskPackageRecurrence = { type: form.recurrenceType };
  if (form.recurrenceType === "monthly") recurrence.day_of_month = Number(form.dayOfMonth);
  if (form.recurrenceType === "weekly") recurrence.weekday = Number(form.weekday);
  if (form.recurrenceType === "events") recurrence.event_tag = form.eventTag.trim();
  const dueRule: TaskPackageDueRule = { type: form.dueType };
  if (form.dueType === "fixed") {
    dueRule.day = Number(form.dueDay);
    dueRule.month = Number(form.dueMonth);
  }
  if (form.dueType === "offset") {
    const days = Math.abs(Number(form.offsetDays) || 0);
    dueRule.offset_days = form.offsetDirection === "before" ? -days : days;
  }
  return {
    task: form.task.trim(),
    reference_link: form.referenceLink.trim() || null,
    tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
    responsible: form.responsible,
    recurrence,
    due_rule: dueRule,
  };
}

export function TaskPackageItemModal({
  open,
  item,
  responsibleLists,
  entriesByList,
  participants,
  eventTags,
  onClose,
  onSave,
}: {
  open: boolean;
  item: TaskPackageItem | null;
  responsibleLists: StructuredListDefinition[];
  entriesByList: Record<string, StructuredListEntry[]>;
  participants: ParticipantSummary[];
  eventTags: string[];
  onClose: () => void;
  onSave: (payload: TaskPackageItemPayload) => Promise<void>;
}) {
  const t = useTranslations("taskPackages");
  const tCommon = useTranslations("common");
  const [form, setForm] = useState<FormState>(() => formFromItem(item));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const initial = formFromItem(item);
    setForm(initial);
  }, [open, item]);

  const participantsById = useMemo(() => new Map(participants.map((participant) => [participant.id, participant])), [participants]);
  const context: ResponsibleContext = useMemo(
    () => ({ listsById: new Map(responsibleLists.map((definition) => [definition.id, definition])), entriesByList, participantsById }),
    [responsibleLists, entriesByList, participantsById]
  );
  // Zeilen aller passenden Listen in einer Auswahl; der Listenname steht nur davor, wenn es mehrere gibt.
  const entryOptions: EntryOption[] = useMemo(() => {
    const options: EntryOption[] = [];
    for (const definition of responsibleLists) {
      const meta = eligibleResponsibleList(definition);
      for (const entry of entriesByList[definition.id] ?? []) {
        const label = meta ? entryLabel(entry, meta, participantsById, t) : entry.id;
        options.push({
          key: entryKey(definition.id, entry.id),
          listId: definition.id,
          entryId: entry.id,
          label: responsibleLists.length > 1 ? t("entryWithList", { list: definition.name, entry: label }) : label,
        });
      }
    }
    return options;
  }, [responsibleLists, entriesByList, participantsById, t]);
  const selectedEntryKeys = form.responsible
    .filter((entry) => entry.list_definition_id && entry.list_entry_id)
    .map((entry) => entryKey(entry.list_definition_id ?? "", entry.list_entry_id ?? ""));
  const fixedParticipantIds = form.responsible.filter((entry) => entry.participant_id).map((entry) => entry.participant_id ?? "");
  const offsetAnchor = form.recurrenceType === "once" ? t("anchor.cycleStart") : form.recurrenceType === "events" ? t("anchor.event") : t("anchor.occurrence");

  // Reihenfolge der bestehenden Verantwortlichen bleibt erhalten, neu gewählte kommen ans Ende.
  function setEntries(keys: string[]) {
    const wanted = new Set(keys);
    const kept = form.responsible.filter((entry) => entry.participant_id || wanted.has(entryKey(entry.list_definition_id ?? "", entry.list_entry_id ?? "")));
    const existing = new Set(selectedEntryKeys);
    const added = entryOptions
      .filter((option) => wanted.has(option.key) && !existing.has(option.key))
      .map((option) => ({ list_definition_id: option.listId, list_entry_id: option.entryId }));
    setForm({ ...form, responsible: [...kept, ...added] });
  }

  function setFixedParticipants(ids: string[]) {
    const wanted = new Set(ids);
    const kept = form.responsible.filter((entry) => !entry.participant_id || wanted.has(entry.participant_id));
    const existing = new Set(fixedParticipantIds);
    const added = ids.filter((id) => !existing.has(id)).map((id) => ({ participant_id: id }));
    setForm({ ...form, responsible: [...kept, ...added] });
  }

  // Ein festes Datum gibt es nur bei "Einmal pro Zyklus" - beim Wechsel fällt es auf "Keine" zurück.
  function setRecurrenceType(type: TaskPackageRecurrenceType) {
    const dueType = type !== "once" && form.dueType === "fixed" ? "none" : form.dueType;
    setForm({ ...form, recurrenceType: type, dueType });
  }

  function removeResponsible(index: number) {
    setForm({ ...form, responsible: form.responsible.filter((_, position) => position !== index) });
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSave(payloadFromForm(form));
    } finally {
      setSaving(false);
    }
  }

  const fixedNotAllowed = form.dueType === "fixed" && form.recurrenceType !== "once";
  const valid = form.task.trim().length > 0 && !fixedNotAllowed && (form.recurrenceType !== "events" || form.eventTag.trim().length > 0);

  return (
    <Modal open={open} title={item ? t("itemEditTitle") : t("itemCreateTitle")} onClose={onClose} size="wide">
      <ModalSaveForm className="grid task-package-form" onSubmit={handleSubmit}>
        <label className="field-stack">
          <span className="field-label">{t("taskLabel")}</span>
          <input value={form.task} onChange={(event) => setForm({ ...form, task: event.target.value })} placeholder={t("taskPlaceholder")} required autoFocus />
        </label>

        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("linkLabel")}</span>
            <input type="url" value={form.referenceLink} onChange={(event) => setForm({ ...form, referenceLink: event.target.value })} />
          </label>
          <div className="field-stack">
            <span className="field-label">{t("tagsLabel")}</span>
            <TagInput value={form.tags} onChange={(value) => setForm({ ...form, tags: value })} />
          </div>
        </div>

        <div className="field-stack">
          <span className="field-label">{t("responsibleTitle")}</span>
          <div className="task-package-responsible-box">
            {form.responsible.map((entry, index) => (
              <span key={`${entry.list_entry_id ?? entry.participant_id}-${index}`} className="task-package-chip">
                <Badge variant={entry.participant_id ? "neutral" : "info"}>{responsibleLabel(entry, context, t)}</Badge>
                <button
                  type="button"
                  className="button-icon-soft button-icon-soft-sm"
                  aria-label={t("removeResponsible", { name: responsibleLabel(entry, context, t) })}
                  onClick={() => removeResponsible(index)}
                >
                  <ActionIcon name="close" />
                </button>
              </span>
            ))}
            {form.responsible.length === 0 ? <span className="muted task-package-responsible-empty">{t("responsibleNone")}</span> : null}
            <span className="task-package-responsible-add">
              {entryOptions.length > 0 ? (
                <SearchableMultiSelect
                  options={entryOptions}
                  getId={(option) => option.key}
                  getLabel={(option) => option.label}
                  values={selectedEntryKeys}
                  onChange={setEntries}
                  triggerLabel={t("addEntry")}
                  className="task-package-add-trigger"
                />
              ) : null}
              <SearchableMultiSelect
                options={participants}
                getId={(participant) => participant.id}
                getLabel={(participant) => participant.display_name}
                values={fixedParticipantIds}
                onChange={setFixedParticipants}
                triggerLabel={t("addPerson")}
                className="task-package-add-trigger"
              />
            </span>
          </div>
          <span className="field-help">{responsibleLists.length > 0 ? t("responsibleHelp") : t("noResponsibleLists")}</span>
        </div>

        <div className="field-stack" role="radiogroup" aria-label={t("recurrenceLabel")}>
          <span className="field-label">{t("recurrenceLabel")}</span>
          <div className="role-picker">
            {RECURRENCE_TYPES.map((type) => (
              <label key={type} className="role-picker-option">
                <input type="radio" name="task-package-recurrence" value={type} checked={form.recurrenceType === type} onChange={() => setRecurrenceType(type)} />
                {t(`recurrenceType.${type}`)}
              </label>
            ))}
          </div>
          {form.recurrenceType === "monthly" ? (
            <label className="field-stack task-package-subfield">
              <span className="field-label">{t("dayOfMonthLabel")}</span>
              <input type="number" min={1} max={31} required value={form.dayOfMonth} onChange={(event) => setForm({ ...form, dayOfMonth: event.target.value })} />
              <span className="field-help">{t("dayOfMonthHelp")}</span>
            </label>
          ) : null}
          {form.recurrenceType === "weekly" ? (
            <label className="field-stack task-package-subfield">
              <span className="field-label">{t("weekdayLabel")}</span>
              <select value={form.weekday} onChange={(event) => setForm({ ...form, weekday: event.target.value })}>
                {WEEKDAYS.map((weekday) => (
                  <option key={weekday} value={weekday}>
                    {t(`weekdays.${weekday}`)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {form.recurrenceType === "events" ? (
            <div className="field-stack task-package-subfield">
              <span className="field-label">{t("eventTagLabel")}</span>
              <TagInput
                value={form.eventTag}
                onChange={(value) => setForm({ ...form, eventTag: value })}
                suggestions={eventTags}
                multi={false}
                placeholder={t("eventTagPlaceholder")}
              />
              <span className="field-help">{t("eventTagHelp")}</span>
            </div>
          ) : null}
        </div>

        <div className="field-stack" role="radiogroup" aria-label={t("dueLabel")}>
          <span className="field-label">{t("dueLabel")}</span>
          <div className="role-picker">
            {DUE_TYPES.map((type) => (
              <label key={type} className="role-picker-option">
                <input
                  type="radio"
                  name="task-package-due"
                  value={type}
                  checked={form.dueType === type}
                  disabled={type === "fixed" && form.recurrenceType !== "once"}
                  onChange={() => setForm({ ...form, dueType: type })}
                />
                {t(`dueType.${type}`)}
              </label>
            ))}
          </div>
          {form.recurrenceType !== "once" ? <span className="field-help">{t("fixedOnlyOnceHint")}</span> : null}
          {form.dueType === "fixed" ? (
            <div className="two-col task-package-subfield">
              <label className="field-stack">
                <span className="field-label">{t("dueDayLabel")}</span>
                <input type="number" min={1} max={31} required value={form.dueDay} onChange={(event) => setForm({ ...form, dueDay: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("dueMonthLabel")}</span>
                <select value={form.dueMonth} onChange={(event) => setForm({ ...form, dueMonth: event.target.value })}>
                  {MONTHS.map((month) => (
                    <option key={month} value={month}>
                      {t(`months.${month}`)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
          {form.dueType === "offset" ? (
            <div className="two-col task-package-subfield">
              <label className="field-stack">
                <span className="field-label">{t("offsetDaysLabel")}</span>
                <input type="number" min={0} max={366} required value={form.offsetDays} onChange={(event) => setForm({ ...form, offsetDays: event.target.value })} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("offsetDirectionLabel")}</span>
                <select value={form.offsetDirection} onChange={(event) => setForm({ ...form, offsetDirection: event.target.value as "after" | "before" })}>
                  <option value="after">{t("offsetAfter", { anchor: offsetAnchor })}</option>
                  <option value="before">{t("offsetBefore", { anchor: offsetAnchor })}</option>
                </select>
              </label>
            </div>
          ) : null}
        </div>

        <p className="field-help">{t("propagationHelp")}</p>

        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {tCommon("cancel")}
          </button>
          <button type="submit" className="button-primary" disabled={!valid || saving}>
            {saving ? t("saving") : t("saveItem")}
          </button>
        </div>
      </ModalSaveForm>
    </Modal>
  );
}
