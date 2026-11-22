// Auswahl-Liste und Fehlermeldung des Upload-Formulars sind für Screenreader bedienbar
// (Nachtlauf 2026-11-22): vorher hiessen alle Entfernen-Knöpfe nur «Entfernen» und eine
// abgelehnte Auswahl («zu gross», «Typ nicht erlaubt») wurde nicht angesagt.
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { UploadErrorMessage, UploadFileList } from "@/components/upload-file-list";
import { locales } from "@/i18n/locale-config.generated";

function messagesFor(locale: string) {
  const file = path.join(__dirname, "..", "messages", locale, "abgabebox.json");
  return { abgabebox: JSON.parse(fs.readFileSync(file, "utf-8")) };
}

function render(locale: string, node: React.ReactNode) {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} timeZone="Europe/Zurich" messages={messagesFor(locale)}>
      {node}
    </NextIntlClientProvider>
  );
}

const files = [new File(["a"], "bericht.pdf"), new File(["b"], "foto.jpg")];

describe.each(locales)("UploadFileList (%s)", (locale) => {
  it("names the file in each remove button", () => {
    const html = render(locale, <UploadFileList files={files} onRemove={() => {}} />);
    const labels = [...html.matchAll(/aria-label="([^"]*)"/g)].map((m) => m[1]);
    expect(labels).toHaveLength(2);
    expect(labels[0]).toContain("bericht.pdf");
    expect(labels[1]).toContain("foto.jpg");
  });
});

describe("UploadErrorMessage", () => {
  it("announces errors as alert", () => {
    expect(render("de", <UploadErrorMessage message="zu gross" />)).toBe('<p class="error" role="alert">zu gross</p>');
  });

  it("renders nothing without message", () => {
    expect(render("de", <UploadErrorMessage message={null} />)).toBe("");
  });
});
