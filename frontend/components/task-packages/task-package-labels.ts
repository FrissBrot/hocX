import { formatDate } from "@/lib/utils/format";
import { EligibleResponsibleList, eligibleResponsibleList, listParticipantIds, listTextValue } from "@/lib/utils/responsible-lists";
import {
  CycleConfigSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  TaskPackageDueRule,
  TaskPackageRecurrence,
  TaskPackageResponsible,
} from "@/types/api";

// Reine Hilfsfunktionen ohne eigene Komponente: `t` kommt vom Aufrufer
// (useTranslations("taskPackages")), siehe section-tabs.ts für dasselbe Muster.
export type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

/** Startjahr des Zyklus, in dem `today` liegt - gleiche Regel wie cycle_utils.get_cycle_year im Backend. */
export function currentCycleYear(config: Pick<CycleConfigSummary, "reset_month" | "reset_day">, today: Date = new Date()): number {
  const boundary = (year: number) => {
    const lastDay = new Date(year, config.reset_month, 0).getDate();
    return new Date(year, config.reset_month - 1, Math.min(config.reset_day, lastDay));
  };
  const day = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const thisYear = boundary(day.getFullYear());
  const start = day <= thisYear ? boundary(day.getFullYear() - 1) : thisYear;
  start.setDate(start.getDate() + 1);
  return start.getFullYear();
}

export function weekdayLabel(weekday: number, t: TFunc): string {
  return t(`weekdays.${weekday}`);
}

export function recurrenceLabel(recurrence: TaskPackageRecurrence, t: TFunc): string {
  switch (recurrence.type) {
    case "monthly":
      return t("recurrenceSummary.monthly", { day: recurrence.day_of_month ?? 1 });
    case "weekly":
      return t("recurrenceSummary.weekly", { weekday: weekdayLabel(recurrence.weekday ?? 0, t) });
    case "events":
      return t("recurrenceSummary.events", { tag: recurrence.event_tag ?? "" });
    default:
      return t("recurrenceSummary.once");
  }
}

export function dueRuleLabel(dueRule: TaskPackageDueRule, recurrence: TaskPackageRecurrence, t: TFunc): string {
  if (dueRule.type === "fixed") {
    const day = String(dueRule.day ?? 1).padStart(2, "0");
    const month = String(dueRule.month ?? 1).padStart(2, "0");
    return t("dueSummary.fixed", { date: `${day}.${month}.` });
  }
  if (dueRule.type === "offset") {
    const anchor = recurrence.type === "once" ? t("anchor.cycleStart") : recurrence.type === "events" ? t("anchor.event") : t("anchor.occurrence");
    const days = dueRule.offset_days ?? 0;
    if (days === 0) return t("dueSummary.sameDay", { anchor });
    return days > 0 ? t("dueSummary.after", { days, anchor }) : t("dueSummary.before", { days: -days, anchor });
  }
  return t("dueSummary.none");
}

export type ResponsibleContext = {
  listsById: Map<string, StructuredListDefinition>;
  entriesByList: Record<string, StructuredListEntry[]>;
  participantsById: Map<string, ParticipantSummary>;
};

/** Ämtli-Zeile als "Lagerleitung (Anna, Ben)", feste Person als Name. */
export function responsibleLabel(responsible: TaskPackageResponsible, context: ResponsibleContext, t: TFunc): string {
  if (responsible.participant_id) {
    return context.participantsById.get(responsible.participant_id)?.display_name ?? t("unknownPerson");
  }
  const definition = responsible.list_definition_id ? context.listsById.get(responsible.list_definition_id) : undefined;
  const meta = definition ? eligibleResponsibleList(definition) : null;
  const entry = context.entriesByList[responsible.list_definition_id ?? ""]?.find((item) => item.id === responsible.list_entry_id);
  if (!meta || !entry) {
    return t("unknownEntry");
  }
  return entryLabel(entry, meta, context.participantsById, t);
}

export function entryLabel(
  entry: StructuredListEntry,
  meta: EligibleResponsibleList,
  participantsById: Map<string, ParticipantSummary>,
  t: TFunc
): string {
  const text = listTextValue(entry, meta.textColumn) || t("emptyRow");
  const names = listParticipantIds(entry, meta.participantColumn, meta.participantValueType)
    .map((id) => participantsById.get(id)?.display_name)
    .filter((name): name is string => !!name);
  return names.length ? t("entryWithPeople", { entry: text, people: names.join(", ") }) : text;
}

export function previewDate(value: string | null): string {
  return formatDate(value) ?? "—";
}
