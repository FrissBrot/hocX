// Abschluss des Word-Imports: die Zusammenfassung («… wurden übernommen», «… übersprungen») und der
// Zähler der Analyse-Hinweise standen fest deutsch im Assistenten, mit Plural per Konkatenation.
import fs from "node:fs";
import path from "node:path";

import { render } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { locales } from "@/i18n/locale-config.generated";

import { WordImportDoneStats } from "./word-import-wizard";

function messagesFor(locale: string) {
  const dir = path.join(process.cwd(), "messages", locale);
  return Object.fromEntries(
    fs
      .readdirSync(dir)
      .filter((name) => name.endsWith(".json"))
      .map((name) => [name.slice(0, -".json".length), JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"))])
  );
}

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const dir = path.join(process.cwd(), "messages", "en");
  const messages = Object.fromEntries(
    fs
      .readdirSync(dir)
      .filter((name) => name.endsWith(".json"))
      .map((name) => [name.slice(0, -".json".length), JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"))])
  );
  return { ...actual, useTranslations: (namespace?: string) => actual.createTranslator({ locale: "en", messages, namespace }), useLocale: () => "en" };
});

describe("WordImportDoneStats", () => {
  it("summarises the import in the UI language", () => {
    const { container } = render(<WordImportDoneStats summary={{ attendance: 12, events: 1, lists: 3, matrices: 0, skipped: 2, warnings: [] }} />);
    expect(container.textContent).toBe("12 attendance records, 1 event, 3 list entries and 0 matrix values were imported. 2 entries were skipped and can be added manually.");
  });

  it("omits the skipped sentence when nothing was skipped", () => {
    const { container } = render(<WordImportDoneStats summary={{ attendance: 1, events: 0, lists: 0, matrices: 1, skipped: 0, warnings: [] }} />);
    expect(container.textContent).not.toMatch(/skipped/);
  });
});

describe.each(locales)("word import summary messages (%s)", (locale) => {
  const t = createTranslator({ locale, messages: messagesFor(locale), namespace: "tools.wordImport" as never }) as unknown as (
    key: string,
    values?: Record<string, number>
  ) => string;

  it("formats every count with singular and plural", () => {
    const summary = t("doneSummary", { attendance: 7, events: 8, lists: 9, matrices: 6 });
    for (const value of ["7", "8", "9", "6"]) expect(summary).toContain(value);
    expect(t("doneSkipped", { count: 1 })).not.toBe(t("doneSkipped", { count: 2 }).replace("2", "1"));
    expect(t("analysisWarnings", { count: 1 })).not.toBe(t("analysisWarnings", { count: 2 }).replace("2", "1"));
  });
});
