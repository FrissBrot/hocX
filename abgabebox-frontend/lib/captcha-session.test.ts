import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { clearCaptchaSession, readCaptchaSession, storeCaptchaSession } from "./captcha-session";

describe("captcha-session", () => {
  // Der Speicher arbeitet nur im Browser (Server: geteiltes Modul), Tests laufen ohne DOM
  beforeAll(() => vi.stubGlobal("window", {}));
  afterAll(() => vi.unstubAllGlobals());

  it("gibt das Token je Link bis kurz vor Ablauf zurück", () => {
    storeCaptchaSession("link-a", "token-a", 7200, 0);
    expect(readCaptchaSession("link-a", 1000)).toBe("token-a");
    expect(readCaptchaSession("link-b", 1000)).toBeNull();
    // Eine Minute Puffer vor dem Ablauf
    expect(readCaptchaSession("link-a", 7200_000 - 30_000)).toBeNull();
  });

  it("vergisst das Token nach clear", () => {
    storeCaptchaSession("link-c", "token-c", 7200);
    clearCaptchaSession("link-c");
    expect(readCaptchaSession("link-c")).toBeNull();
  });

  it("speichert auf dem Server nichts", () => {
    vi.unstubAllGlobals();
    storeCaptchaSession("link-d", "token-d", 7200);
    vi.stubGlobal("window", {});
    expect(readCaptchaSession("link-d")).toBeNull();
  });
});
