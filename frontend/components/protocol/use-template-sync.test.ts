import { describe, expect, it } from "vitest";

import { templateChangedSinceSync } from "./use-template-sync";

describe("templateChangedSinceSync", () => {
  const base = { status: "geplant", template_version: 1, template_latest_version: 2 };

  it("shows the hint for planned and prepared protocols with an older template version", () => {
    expect(templateChangedSinceSync(base)).toBe(true);
    expect(templateChangedSinceSync({ ...base, status: "vorbereitet" })).toBe(true);
  });

  it("hides the hint once the protocol is up to date", () => {
    expect(templateChangedSinceSync({ ...base, template_version: 2 })).toBe(false);
    expect(templateChangedSinceSync({ ...base, template_latest_version: null })).toBe(false);
    expect(templateChangedSinceSync({ ...base, template_latest_version: undefined })).toBe(false);
  });

  it("never shows the hint for held or closed protocols", () => {
    expect(templateChangedSinceSync({ ...base, status: "durchgeführt" })).toBe(false);
    expect(templateChangedSinceSync({ ...base, status: "abgeschlossen" })).toBe(false);
  });
});
