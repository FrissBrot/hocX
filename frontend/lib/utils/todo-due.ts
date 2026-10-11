export const TODO_DUE_PRESETS = ["endOfWeek", "endOfMonth", "inTwoWeeks"] as const;
export type TodoDuePreset = typeof TODO_DUE_PRESETS[number];

/** Kalendertage lokal berechnen, damit Zeitzonen und Sommerzeit das Datum nicht verschieben. */
export function todoDuePresetDate(preset: TodoDuePreset, today = new Date()): string {
  const date = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (preset === "endOfWeek") date.setDate(date.getDate() + (7 - date.getDay()) % 7);
  else if (preset === "endOfMonth") date.setMonth(date.getMonth() + 1, 0);
  else date.setDate(date.getDate() + 14);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
