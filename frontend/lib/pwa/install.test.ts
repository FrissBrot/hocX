import { describe, expect, it } from "vitest";

import { dismissedRecently, INSTALL_DISMISS_MS, installPlatform } from "./install";

describe("Installationshinweis", () => {
  it("erkennt iPhone, iPad (auch als Mac getarnt) und Android, nicht Desktop", () => {
    expect(installPlatform("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari", 5)).toBe("ios");
    expect(installPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari", 5)).toBe("ios");
    expect(installPlatform("Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome Mobile", 5)).toBe("android");
    expect(installPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari", 0)).toBeNull();
    expect(installPlatform("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome", 0)).toBeNull();
  });

  it("bleibt nach dem Schliessen 30 Tage weg", () => {
    const now = 1_800_000_000_000;
    expect(dismissedRecently(null, now)).toBe(false);
    expect(dismissedRecently("kaputt", now)).toBe(false);
    expect(dismissedRecently(String(now - 1000), now)).toBe(true);
    expect(dismissedRecently(String(now - INSTALL_DISMISS_MS - 1), now)).toBe(false);
  });
});
