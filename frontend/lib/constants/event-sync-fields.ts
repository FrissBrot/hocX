// Termin-/Todo-Felder, in die ein Textblock (Vorlagen-Element bzw. Word-Import-Textblock)
// per "Pro Termin"/"Pro Todo"-Rückschreibung direkt hineinschreiben kann, mit ihrer
// deutschen Klartext-Bezeichnung.
//
// Vorher unabhängig doppelt gepflegt in components/template/element-definition-manager.tsx
// (EVENT_SYNC_FIELDS/TODO_SYNC_FIELDS) und dem Word-Import-Wizard, der den rohen
// technischen Feldnamen (z.B. "spezial_text1") anzeigte, weil er keinen Zugriff auf die
// Klartext-Zuordnung hatte. Beide importieren jetzt von hier.
export type SyncFieldOption = { value: string; label: string };

export const EVENT_SYNC_FIELDS: SyncFieldOption[] = [
  { value: "description", label: "Beschreibung" },
  { value: "location", label: "Standort" },
  { value: "spezial_text1", label: "Spezial Text 1" },
  { value: "spezial_text2", label: "Spezial Text 2" },
  { value: "spezial_text3", label: "Spezial Text 3" },
];

export const TODO_SYNC_FIELDS: SyncFieldOption[] = [
  { value: "task", label: "Aufgabentext" },
  { value: "reference_link", label: "Referenz-Link" },
  { value: "due_marker", label: "Fälligkeits-Marker" },
];

// value -> Klartext-Label, für Stellen, die nur die Anzeige-Bezeichnung eines bekannten
// Feldnamens brauchen (z.B. der Hinweis auf das verknüpfte DB-Feld im Word-Import).
export const EVENT_SYNC_FIELD_LABELS: Record<string, string> = Object.fromEntries(
  EVENT_SYNC_FIELDS.map((option) => [option.value, option.label])
);

export const TODO_SYNC_FIELD_LABELS: Record<string, string> = Object.fromEntries(
  TODO_SYNC_FIELDS.map((option) => [option.value, option.label])
);
