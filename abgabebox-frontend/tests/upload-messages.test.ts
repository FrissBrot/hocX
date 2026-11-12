// ICU-Meldungen der Upload-Seite in allen Sprachen formatierbar (Plural/Select, Variablen gefüllt).
import fs from "node:fs";
import path from "node:path";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/locale-config.generated";

function messagesFor(locale: string) {
  const file = path.join(__dirname, "..", "messages", locale, "abgabebox.json");
  return { abgabebox: JSON.parse(fs.readFileSync(file, "utf-8")) };
}

describe.each(locales)("upload messages (%s)", (locale) => {
  const t = createTranslator({ locale, messages: messagesFor(locale), namespace: "abgabebox.upload" as never }) as unknown as (
    key: string,
    values?: Record<string, string | number>
  ) => string;

  it("names the rejected extension and the allowed ones", () => {
    const text = t("errors.unsupportedType", { filename: "setup.exe", extension: "EXE", kind: "extension", allowed: "PDF, JPG" });
    expect(text).toContain("setup.exe");
    expect(text).toContain(".EXE");
    expect(text).toContain("PDF, JPG");
  });

  it("has an own wording for files without an extension", () => {
    const withExt = t("errors.unsupportedType", { filename: "README", extension: "X", kind: "extension", allowed: "PDF" });
    const missing = t("errors.unsupportedType", { filename: "README", extension: "", kind: "missing", allowed: "PDF" });
    expect(missing).not.toBe(withExt);
    expect(missing).toContain("PDF");
  });

  it("uses MB instead of MiB", () => {
    expect(t("hintPerFile", { size: 20 })).toContain("20 MB");
    expect(t("hintTotal")).toContain("MB");
    expect(JSON.stringify(messagesFor(locale))).not.toContain("MiB");
  });

  it("formats the progress percentage", () => {
    expect(t("progressPercent", { percent: 42 })).toContain("42");
  });
});
