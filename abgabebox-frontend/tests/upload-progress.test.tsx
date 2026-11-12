import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { UploadProgress } from "@/components/upload-progress";
import type { UploadPhase } from "@/lib/upload-request";
import de from "@/messages/de/abgabebox.json";

function render(progress: UploadPhase) {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="de" timeZone="Europe/Zurich" messages={{ abgabebox: de }}>
      <UploadProgress progress={progress} />
    </NextIntlClientProvider>
  );
}

describe("UploadProgress", () => {
  it("zeigt beim Senden einen barrierefreien Prozentbalken", () => {
    const html = render({ phase: "uploading", percent: 42 });
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuenow="42"');
    expect(html).toContain('aria-valuemin="0"');
    expect(html).toContain('aria-valuemax="100"');
    expect(html).toContain(`aria-label="${de.upload.progressLabel}"`);
    expect(html).toContain("42 %");
    expect(html).toContain("width:42%");
    expect(html).toContain(de.upload.progressUploading);
  });

  it("wechselt nach dem Senden zu «wird geprüft» ohne Prozentwert", () => {
    const html = render({ phase: "processing" });
    expect(html).toContain('role="progressbar"');
    expect(html).not.toContain("aria-valuenow");
    expect(html).toContain(de.upload.progressProcessing);
    expect(html).toContain(de.upload.progressProcessingHint);
    expect(html).toContain("upload-progress-processing");
  });
});
