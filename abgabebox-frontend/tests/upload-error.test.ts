// Fehlerantworten und Duplikat-Hinweise des Backends erscheinen in der gewählten Sprache
// (Nachtlauf 2026-11-22): vorher wurde das deutsche `detail` bzw. der deutsche Hinweistext
// unverändert angezeigt, auch auf Englisch, Französisch und Italienisch.
import fs from "node:fs";
import path from "node:path";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/locale-config.generated";
import { SERVER_ERROR_CODES, duplicateWarnings, serverErrorMessage } from "@/lib/upload-error";

function messagesFor(locale: string) {
  const file = path.join(__dirname, "..", "messages", locale, "abgabebox.json");
  return { abgabebox: JSON.parse(fs.readFileSync(file, "utf-8")) };
}

function translator(locale: string) {
  return createTranslator({ locale, messages: messagesFor(locale), namespace: "abgabebox.upload" as never }) as unknown as (
    key: string,
    values?: Record<string, string | number>
  ) => string;
}

const SAMPLE_PARAMS = { max: 50, extension: "exe", maxMb: 20, maxFiles: 3, remaining: 1 };

describe.each(locales)("server errors (%s)", (locale) => {
  const t = translator(locale);

  it.each(SERVER_ERROR_CODES)("translates %s", (code) => {
    const text = serverErrorMessage(t, { detail: "Deutscher Rohtext", code, params: SAMPLE_PARAMS });
    expect(text).not.toContain("Deutscher Rohtext");
    expect(text).not.toContain("errors.server");
    expect(text.length).toBeGreaterThan(5);
  });

  it("fills the numbers of too_many_files_total", () => {
    const text = serverErrorMessage(t, { code: "too_many_files_total", params: { maxFiles: 3, remaining: 1 } });
    expect(text).toContain("3");
    expect(text).toContain("1");
  });

  it("falls back to the generic message, never to raw backend text", () => {
    const generic = t("errors.uploadFailedGeneric");
    expect(serverErrorMessage(t, { detail: "Ein interner Fehler ist aufgetreten." })).toBe(generic);
    expect(serverErrorMessage(t, { detail: "x", code: "unbekannt" })).toBe(generic);
    expect(serverErrorMessage(t, null)).toBe(generic);
  });

  it("builds duplicate hints from file names", () => {
    const [hint, ...rest] = duplicateWarnings(t, { image_duplicate_files: ["ferienlager.png"] });
    expect(rest).toEqual([]);
    expect(hint).toContain("ferienlager.png");
  });

  it("uses ICU plural instead of «Datei(en)»", () => {
    expect(t("errors.maxFilesTotal", { maxFiles: 1, remaining: 0 })).not.toMatch(/\(en\)|\(s\)/);
  });
});

it("server messages are not German outside of de", () => {
  for (const locale of locales.filter((l) => l !== "de")) {
    const text = serverErrorMessage(translator(locale), { code: "element_closed" });
    expect(text).not.toBe(serverErrorMessage(translator("de"), { code: "element_closed" }));
  }
  expect(duplicateWarnings(translator("en"), { image_duplicate_files: ["a.png"] })[0]).not.toContain("ähnelt");
});
