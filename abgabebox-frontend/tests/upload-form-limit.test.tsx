// Upload-Seite eines Dokuments, dessen Dateikontingent schon ausgeschöpft ist (Nachtlauf
// 2026-11-22): vorher erschien das volle Formular mit «max. 0 weitere Dateien», jede Auswahl
// wurde abgelehnt. Jetzt ein klarer Hinweis ohne Ablagefläche.
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import de from "@/messages/de/abgabebox.json";

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

import { UploadForm } from "@/components/upload-form";

function render(props: { maxFiles: number | null; alreadyUploadedCount: number; singleElement?: boolean }) {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="de" timeZone="Europe/Zurich" messages={{ abgabebox: de }}>
      <UploadForm
        linkToken="tok"
        assignmentSlug="fotos"
        elementRef="event-1"
        assignmentTitle="Fotos"
        elementLabel="Hock"
        allowedFileTypes={["jpg"]}
        maxFileSizeMb={20}
        sitekey=""
        {...props}
      />
    </NextIntlClientProvider>
  );
}

describe("UploadForm bei ausgeschöpftem Kontingent", () => {
  it("zeigt keinen Upload, sondern den Hinweis", () => {
    const html = render({ maxFiles: 3, alreadyUploadedCount: 3 });
    expect(html).not.toContain("drop-zone");
    expect(html).not.toContain('type="submit"');
    expect(html).toContain(de.upload.limitReachedTitle);
    expect(html).toContain("alle 3 erlaubten Dateien");
    expect(html).toContain('href="/tok/fotos"');
    expect(html).toContain('href="/tok"');
  });

  it("verlinkt bei nur einem Dokument nicht auf die Dokumentauswahl", () => {
    const html = render({ maxFiles: 1, alreadyUploadedCount: 1, singleElement: true });
    expect(html).not.toContain('href="/tok/fotos"');
    expect(html).toContain('href="/tok"');
  });

  it("zeigt das Formular, solange noch Dateien möglich sind", () => {
    expect(render({ maxFiles: 3, alreadyUploadedCount: 2 })).toContain("drop-zone");
    expect(render({ maxFiles: null, alreadyUploadedCount: 40 })).toContain("drop-zone");
  });
});
