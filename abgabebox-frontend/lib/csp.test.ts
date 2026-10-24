import { describe, expect, it } from "vitest";

import { captchaConnectOrigin, contentSecurityPolicy } from "@/lib/csp";
import { FRIENDLY_CAPTCHA_PUZZLE_ENDPOINT, resolvePuzzleEndpoint } from "@/lib/friendly-captcha";

describe("Captcha-Endpunkt (Datenschutz-Audit E2)", () => {
  it("nimmt den EU-Endpunkt aus der Umgebung und erlaubt nur ihn in connect-src", () => {
    const eu = "https://eu-api.friendlycaptcha.eu/api/v1/puzzle";
    expect(resolvePuzzleEndpoint(eu)).toBe(eu);
    expect(contentSecurityPolicy("n", false, captchaConnectOrigin(eu))).toContain("connect-src 'self' https://eu-api.friendlycaptcha.eu;");
  });

  it("fällt bei fehlendem oder unsicherem Wert auf den globalen Endpunkt zurück", () => {
    expect(resolvePuzzleEndpoint(undefined)).toBe(FRIENDLY_CAPTCHA_PUZZLE_ENDPOINT);
    expect(resolvePuzzleEndpoint("http://example.org/puzzle")).toBe(FRIENDLY_CAPTCHA_PUZZLE_ENDPOINT);
    expect(captchaConnectOrigin("")).toBe("https://api.friendlycaptcha.com");
  });
});
