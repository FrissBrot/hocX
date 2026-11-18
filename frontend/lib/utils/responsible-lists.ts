import { StructuredListDefinition, StructuredListEntry } from "@/types/api";

// Listen, deren Zeilen Verantwortliche liefern (z. B. eine Ämtliliste): die Spalte mit der Rolle
// «Bezeichnung» benennt die Zeile, die Spalte mit der Rolle «Verantwortliche» liefert die Personen
// (Migration 0186; ohne Rollen: erste Text- bzw. erste Personen-Spalte). Gemeinsam genutzt von den
// Verantwortlichen im Protokoll-Vorlagen-Editor (template-builder.tsx) und den Aufgabenpaketen; das
// Backend löst dieselbe Regel in responsible_label_service bzw. services/list_columns.py auf.

export type EligibleResponsibleList = {
  definition: StructuredListDefinition;
  /** Spalten-Key der Bezeichnung */
  textColumn: string;
  /** Spalten-Key der Verantwortlichen */
  participantColumn: string;
  participantValueType: "participant" | "participants";
};

const isPersonType = (type: string) => type === "participant" || type === "participants";

export function eligibleResponsibleList(definition: StructuredListDefinition): EligibleResponsibleList | null {
  const columns = [...definition.columns].sort((left, right) => left.sort_index - right.sort_index);
  const byId = (id: string | null) => columns.find((column) => column.id === id) ?? null;
  const responsible =
    (byId(definition.responsible_column_id) && isPersonType(byId(definition.responsible_column_id)!.value_type) ? byId(definition.responsible_column_id) : null)
    ?? columns.find((column) => isPersonType(column.value_type)) ?? null;
  const label =
    (byId(definition.label_column_id)?.value_type === "text" ? byId(definition.label_column_id) : null)
    ?? columns.find((column) => column.value_type === "text") ?? null;
  if (!responsible || !label) return null;
  return {
    definition,
    textColumn: label.id,
    participantColumn: responsible.id,
    participantValueType: responsible.value_type === "participant" ? "participant" : "participants",
  };
}

export function listTextValue(entry: StructuredListEntry, column: string) {
  return String(entry.values?.[column]?.text_value ?? "").trim();
}

export function listParticipantIds(
  entry: StructuredListEntry,
  column: string,
  valueType: "participant" | "participants"
): string[] {
  const value = entry.values?.[column];
  if (valueType === "participant") {
    const participantId = typeof value?.participant_id === "string" ? value.participant_id : null;
    return participantId ? [participantId] : [];
  }
  return Array.isArray(value?.participant_ids) ? value.participant_ids.filter((id): id is string => typeof id === "string") : [];
}
