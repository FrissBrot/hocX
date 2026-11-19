// Word-Import: Analyse-/Importhinweise kamen nur als deutscher Text aus dem Backend und erschienen
// so auch in der englischen, französischen und italienischen Oberfläche.
import fs from "node:fs";
import path from "node:path";

import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/locale-config.generated";

import { translateWordImportWarnings, type WordImportWarningDetail } from "./word-import-warnings";

// Spiegel der Codes in backend/app/services/word_import_service.py (warnings.add / commit_warnings.add).
const CODES: Record<string, Record<string, string | number>> = {
  elementNotFound: { heading: "Kasse" },
  reviewEventUnmatched: { heading: "Rückblick" },
  fieldsNotDetected: { heading: "Formular" },
  participantNotFound: { name: "Total" },
  eventsToReview: {},
  tableListNotFound: { table: 2 },
  listBlockMissing: { list: "Ämtli" },
  listParticipantsNotFound: { list: "Ämtli", names: "Anna, Ben" },
  tableMatrixNotFound: { table: 3 },
  matrixColumnsByPosition: { matrix: "Plan" },
  matrixRowUnmatched: { matrix: "Plan", row: "Grill" },
  matrixColumnUnmatched: { matrix: "Plan", column: "Mai" },
  matrixRowTypeUnsupported: { matrix: "Plan", row: "Grill" },
  matrixParticipantsNotFound: { matrix: "Plan", names: "Anna" },
  matrixColumnsUncertain: { matrix: "Plan" },
  dateNotDetected: {},
  sectionNoBlock: { heading: "Varia" },
  sectionBlockConflict: { heading: "Varia", other: "Diverses" },
  eventFieldNotOverwritten: { heading: "Varia", field: "description" },
  sectionNotWritable: { heading: "Varia" },
  matrixCellInvalidKey: { row: "r1", column: "Mai" },
  matrixCellNoBlock: { row: "r1", column: "Mai" },
};

function translatorFor(locale: string) {
  const file = path.join(process.cwd(), "messages", locale, "tools.json");
  const messages = { tools: JSON.parse(fs.readFileSync(file, "utf-8")) };
  return createTranslator({ locale, messages, namespace: "tools.wordImport" as never }) as unknown as Parameters<typeof translateWordImportWarnings>[2];
}

describe.each(locales)("word import warnings (%s)", (locale) => {
  const t = translatorFor(locale);

  it("translates every warning code with its parameters", () => {
    const details: WordImportWarningDetail[] = Object.entries(CODES).map(([code, params]) => ({ code, params }));
    const texts = details.map((detail) => `de:${detail.code}`);
    const translated = translateWordImportWarnings(texts, details, t, (field) => `<${field}>`);
    translated.forEach((text, index) => {
      expect(text).not.toBe(texts[index]);
      for (const [name, value] of Object.entries(details[index].params)) {
        expect(text).toContain(name === "field" ? `<${value}>` : String(value));
      }
    });
  });
});

describe("translateWordImportWarnings", () => {
  const t = translatorFor("en");

  it("translates into the UI language", () => {
    expect(translateWordImportWarnings(["Kein passender Teilnehmer für \"Total\" gefunden."], [{ code: "participantNotFound", params: { name: "Total" } }], t)).toEqual([
      "No matching participant found for “Total”.",
    ]);
  });

  it("falls back to the original text for old analyses and unknown codes", () => {
    expect(translateWordImportWarnings(["Alter Hinweis"], undefined, t)).toEqual(["Alter Hinweis"]);
    expect(translateWordImportWarnings(["Neuer Hinweis"], [{ code: "somethingNew", params: {} }], t)).toEqual(["Neuer Hinweis"]);
    // Anzahl passt nicht (z. B. Snapshot teilweise migriert) -> nichts zuordnen
    expect(translateWordImportWarnings(["a", "b"], [{ code: "dateNotDetected", params: {} }], t)).toEqual(["a", "b"]);
  });
});
