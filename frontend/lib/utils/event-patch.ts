import type { EventPatch, EventRoleField, EventSummary } from "@/types/api";

/**
 * Person in einer Rollenliste an-/abwählen. Schickt neben der neuen Liste den Ausgangsstand mit:
 * der Server übernimmt nur die Differenz, eine gleichzeitig von jemand anderem hinzugefügte Person
 * geht so nicht verloren.
 */
export function toggleRolePatch(event: Pick<EventSummary, EventRoleField>, field: EventRoleField, participantId: string): EventPatch {
  const current = event[field] ?? [];
  const next = current.includes(participantId) ? current.filter((id) => id !== participantId) : [...current, participantId];
  return { [field]: next, role_ids_base: { [field]: current } };
}

const ROLE_FIELDS: readonly string[] = ["organizer_ids", "leadership_ids", "participant_ids", "spezial1_ids", "spezial2_ids", "spezial3_ids"];

/**
 * Neue Auswahl für ein Personenfeld des Termins; bei Rollenfeldern mit Ausgangsstand `base`
 * (die Auswahl vor dieser Änderung), damit der Server nur die Differenz übernimmt.
 */
export function eventFieldSelectionPatch(field: string, next: string[], base?: string[]): EventPatch {
  const patch = { [field]: next } as EventPatch;
  if (base && ROLE_FIELDS.includes(field)) patch.role_ids_base = { [field as EventRoleField]: base };
  return patch;
}

/**
 * Zwei noch nicht gesendete Änderungen zusammenfassen. Je Rollenfeld bleibt der älteste
 * Ausgangsstand, sonst ginge die Differenz der ersten Änderung verloren.
 */
export function mergeEventPatches(earlier: EventPatch | undefined, later: EventPatch): EventPatch {
  const merged: EventPatch = { ...(earlier ?? {}), ...later };
  if (earlier?.role_ids_base || later.role_ids_base) {
    merged.role_ids_base = { ...later.role_ids_base, ...earlier?.role_ids_base };
  }
  return merged;
}
