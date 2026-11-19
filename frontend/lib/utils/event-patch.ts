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
  // Ausgangsstand je Feld: der älteste gilt - aber nur, solange auch der spätere Patch für dieses
  // Feld eine Differenz meint. Ersetzt der spätere Patch das Feld bewusst (ohne Ausgangsstand),
  // gilt die Ersetzung (Security-Review 2026-11-19).
  const base: Record<string, string[]> = { ...(earlier?.role_ids_base ?? {}) };
  for (const field of Object.keys(later)) {
    if (field !== "role_ids_base" && !(later.role_ids_base && field in later.role_ids_base)) delete base[field];
  }
  for (const [field, ids] of Object.entries(later.role_ids_base ?? {})) {
    if (!(field in base)) base[field] = ids;
  }
  if (Object.keys(base).length > 0) merged.role_ids_base = base as EventPatch["role_ids_base"];
  else delete merged.role_ids_base;
  return merged;
}
