// Canonical list of template element types (element_type_id -> label/description).
//
// Previously duplicated as two independently-maintained maps:
//   - ELEMENT_TYPE_LABELS in components/template/template-builder.tsx (id -> label only)
//   - elementTypeOptions in components/template/element-definition-manager.tsx (id -> label + description)
// A new element type added to one map but not the other silently showed as "Block #<id>" /
// "Unbekannt (<id>)" in the other screen. Both now import from here instead.
export type ElementTypeOption = {
  value: string;
  label: string;
  description: string;
};

export const ELEMENT_TYPE_OPTIONS: ElementTypeOption[] = [
  { value: "1", label: "Text", description: "Editierbarer Text mit Markdown (fett, kursiv, Listen)" },
  { value: "2", label: "Todo", description: "Checkliste oder Aufgabenliste" },
  { value: "3", label: "Bild", description: "Bild-Upload mit Vorschau" },
  { value: "6", label: "Tabelle", description: "Zeilen mit Labels und typisierten Werten wie Text, Person oder Termin" },
  { value: "7", label: "Terminliste", description: "Gefilterte Liste von Terminen in Tabellenform" },
  { value: "9", label: "Anwesenheit", description: "Anwesenheitsliste für alle Vorlagen-Teilnehmenden" },
  { value: "10", label: "Sitzungsdatum", description: "Setzt das nächste Sitzungsdatum direkt im Protokoll" },
  { value: "11", label: "Matrix", description: "Flexible Matrix mit freien Werten, Personen und automatischen Terminzeilen" },
  { value: "12", label: "Kontostand", description: "Zeigt den aktuellen Kontostand eines Finanzkontos" },
  { value: "13", label: "Transaktionen", description: "Tabelle mit Transaktionen eines Finanzkontos" },
  { value: "14", label: "Bussenliste", description: "Liste der ausstehenden Bussen aus der Anwesenheitskontrolle" },
  { value: "15", label: "Diagramm", description: "Statistik-Diagramm aus vordefinierten Daten (Anwesenheit, Finanzen, Bussen, Gruppen)" },
];

// id -> label only, for spots that just need a display label (e.g. a fallback block title)
// rather than the full option/description list used by the element-type picker.
export const ELEMENT_TYPE_LABELS: Record<number, string> = Object.fromEntries(
  ELEMENT_TYPE_OPTIONS.map((option) => [Number(option.value), option.label])
);
