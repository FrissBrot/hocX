import { StructuredListDefinition, StructuredListEntry } from "@/types/api";

// Listen, deren Zeilen Verantwortliche liefern (z. B. eine Ämtliliste): eine Textspalte für die
// Bezeichnung plus eine Personenspalte. Gemeinsam genutzt von den Verantwortlichen im
// Protokoll-Vorlagen-Editor (template-builder.tsx) und den Aufgabenpaketen; das Backend löst
// dieselbe Form in responsible_label_service._list_entry_participant_ids auf.

export type EligibleResponsibleList = {
  definition: StructuredListDefinition;
  textColumn: "column_one" | "column_two";
  participantColumn: "column_one" | "column_two";
  participantValueType: "participant" | "participants";
};

export function eligibleResponsibleList(definition: StructuredListDefinition): EligibleResponsibleList | null {
  const firstIsText = definition.column_one_value_type === "text";
  const secondIsText = definition.column_two_value_type === "text";
  const firstIsParticipants = definition.column_one_value_type === "participant" || definition.column_one_value_type === "participants";
  const secondIsParticipants = definition.column_two_value_type === "participant" || definition.column_two_value_type === "participants";

  if (firstIsText && secondIsParticipants) {
    return {
      definition,
      textColumn: "column_one",
      participantColumn: "column_two",
      participantValueType: definition.column_two_value_type === "participant" ? "participant" : "participants",
    };
  }
  if (secondIsText && firstIsParticipants) {
    return {
      definition,
      textColumn: "column_two",
      participantColumn: "column_one",
      participantValueType: definition.column_one_value_type === "participant" ? "participant" : "participants",
    };
  }
  return null;
}

export function listTextValue(entry: StructuredListEntry, column: "column_one" | "column_two") {
  const value = column === "column_one" ? entry.column_one_value : entry.column_two_value;
  return String(value?.text_value ?? "").trim();
}

export function listParticipantIds(
  entry: StructuredListEntry,
  column: "column_one" | "column_two",
  valueType: "participant" | "participants"
): string[] {
  const value = column === "column_one" ? entry.column_one_value : entry.column_two_value;
  if (valueType === "participant") {
    const participantId = typeof value?.participant_id === "string" ? value.participant_id : null;
    return participantId ? [participantId] : [];
  }
  return Array.isArray(value?.participant_ids) ? value.participant_ids.filter((id): id is string => typeof id === "string") : [];
}
