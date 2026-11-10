import fs from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createTranslator } from "next-intl";

import { locales } from "@/i18n/locale-config.generated";
import { UploadFileResult } from "@/types/api";
import { UploadResultsModal, uploadFailureText } from "./upload-results-modal";

// IMGMETA-012: Fehlschläge kommen mit Code und werden übersetzt, statt den deutschen Servertext
// in allen Sprachen anzuzeigen.

const SERVER_TEXT = "zu gross (maximal 100 MB)";

function filesTranslator(locale: string) {
  const file = path.join(__dirname, "..", "..", "messages", locale, "files.json");
  const messages = { files: JSON.parse(fs.readFileSync(file, "utf-8")) };
  return createTranslator({ locale, messages, namespace: "files" }) as unknown as (key: string, values?: Record<string, string | number | Date>) => string;
}

const tooLarge: UploadFileResult = { name: "riesig.jpg", status: "failed", message: SERVER_TEXT, code: "too_large", params: { max_mb: 100 } };

describe("uploadFailureText", () => {
  it.each(locales)("translates a failure code with its parameters (%s)", (locale) => {
    const text = uploadFailureText(tooLarge, filesTranslator(locale));
    expect(text).toContain("100");
    expect(text).not.toBe(SERVER_TEXT);
    expect(text).not.toContain("{max_mb}");
  });

  it("falls back to the server text for rule violations and unknown codes", () => {
    const t = filesTranslator("en");
    expect(uploadFailureText({ name: "a.jpg", status: "failed", message: "a.jpg: nur 3 Bilder erlaubt", code: "rule_violation" }, t)).toBe("a.jpg: nur 3 Bilder erlaubt");
    expect(uploadFailureText({ name: "b.jpg", status: "failed", message: "Altes Format" }, t)).toBe("Altes Format");
  });
});

describe("UploadResultsModal", () => {
  it("shows the translated reason instead of the server text", () => {
    render(<UploadResultsModal results={[tooLarge]} onClose={() => {}} noun="images" />);
    expect(screen.getByText("Zu gross (maximal 100 MB).")).toBeTruthy();
    expect(screen.queryByText(SERVER_TEXT)).toBeNull();
  });
});
