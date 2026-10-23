import { describe, expect, it } from "vitest";
import { isRetryableBusy, retryDelaySeconds } from "./upload-retry";

describe("upload-retry", () => {
  it("liest Retry-After und begrenzt die Wartezeit", () => {
    expect(retryDelaySeconds("10")).toBe(10);
    expect(retryDelaySeconds("1")).toBe(3);
    expect(retryDelaySeconds("600")).toBe(30);
    expect(retryDelaySeconds(null)).toBe(10);
    expect(retryDelaySeconds("bald")).toBe(10);
  });

  it("wiederholt nur Auslastung, nicht Wartung oder andere Fehler", () => {
    expect(isRetryableBusy(503, "upload_busy")).toBe(true);
    expect(isRetryableBusy(503, undefined)).toBe(true);
    expect(isRetryableBusy(503, "maintenance")).toBe(false);
    expect(isRetryableBusy(500, "upload_busy")).toBe(false);
  });
});
