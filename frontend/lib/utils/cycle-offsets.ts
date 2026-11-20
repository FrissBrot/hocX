type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

// Zyklen, die ausgewählt werden können: 0 = aktueller Zyklus, -1 = vorheriger usw.
// Eigenes Modul, damit Diagramme (Protokolle) nicht das ganze Abgabe-Formular importieren.
export const CYCLE_OFFSET_OPTIONS = [0, -1, -2, -3];

/** Name eines Zyklus-Versatzes; `t` aus dem Namespace `submissionAssignments`. */
export function cycleOffsetLabel(offset: number, t: TFunc): string {
  return offset === 0 ? t("currentCycle") : offset === -1 ? t("previousCycle") : t("cycleOffsetNamed", { offset: Math.abs(offset) });
}
