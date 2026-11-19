// Hinweise aus Analyse und Import des Word-Imports übersetzen.
//
// Das Backend liefert jeden Hinweis zweimal: als deutschen Text (`warnings`, Fallback für
// gespeicherte Analysen von vor dieser Änderung) und als Code mit Parametern
// (`warning_details`, gleiche Reihenfolge). Übersetzt wird unter `tools.wordImport.warning.<code>`.

export type WordImportWarningDetail = { code: string; params: Record<string, string | number> };

type WarningTFunc = {
  (key: string, values?: Record<string, string | number>): string;
  has: (key: string) => boolean;
};

/** Übersetzte Hinweistexte; `t` aus useTranslations("tools.wordImport"). `fieldLabel` übersetzt den
 * Parameter `field` (Rückschreib-Feld eines Termins, siehe syncFieldLabel). Unbekannte Codes oder
 * fehlende Details fallen auf den deutschen Originaltext zurück. */
export function translateWordImportWarnings(
  warnings: string[],
  details: WordImportWarningDetail[] | undefined,
  t: WarningTFunc,
  fieldLabel?: (field: string) => string
): string[] {
  const usable = details && details.length === warnings.length ? details : null;
  return warnings.map((text, index) => {
    const detail = usable?.[index];
    if (!detail) return text;
    const key = `warning.${detail.code}`;
    if (!t.has(key)) return text;
    const params = { ...detail.params };
    if (fieldLabel && typeof params.field === "string") params.field = fieldLabel(params.field);
    return t(key, params);
  });
}
