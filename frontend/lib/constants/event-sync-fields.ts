// Termin-/Todo-Felder, in die ein Textblock (Vorlagen-Element bzw. Word-Import-Textblock)
// per "Pro Termin"/"Pro Todo"-Rückschreibung direkt hineinschreiben kann.
//
// Nur die Feldnamen (Keys); die Bezeichnungen liegen in den Übersetzungen
// (templates.elementEditor.syncField.<key>), siehe syncFieldLabel.
export const EVENT_SYNC_FIELD_KEYS = ["description", "location", "spezial_text1", "spezial_text2", "spezial_text3"] as const;
export const TODO_SYNC_FIELD_KEYS = ["task", "reference_link", "due_marker"] as const;

type TFunc = (key: string) => string;

/** Bezeichnung eines Rückschreib-Feldes; `t` aus useTranslations("templates.elementEditor"). */
export function syncFieldLabel(field: string, t: TFunc): string {
  return (EVENT_SYNC_FIELD_KEYS as readonly string[]).includes(field) || (TODO_SYNC_FIELD_KEYS as readonly string[]).includes(field)
    ? t(`syncField.${field}`)
    : field;
}
