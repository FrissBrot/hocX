import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { apiErrorCode, apiErrorMessage } from "./error-message";

function fakeT(messages: Record<string, string>) {
  const t = ((key: string) => messages[key] ?? key) as ((key: string) => string) & { has: (key: string) => boolean };
  t.has = (key: string) => key in messages;
  return t;
}

describe("apiErrorMessage", () => {
  const t = fakeT({ "apiErrors.last_admin": "The last administrator cannot be removed" });

  it("übersetzt einen bekannten Code", () => {
    const error = new ApiError("Der letzte Administrator …", "conflict", 409, { code: "last_admin", message: "Der letzte Administrator …" });
    expect(apiErrorCode(error)).toBe("last_admin");
    expect(apiErrorMessage(error, t, "apiErrors", "fallback")).toBe("The last administrator cannot be removed");
  });

  it("nimmt bei unbekanntem Code die Backend-Meldung und sonst den Fallback", () => {
    const unknown = new ApiError("Backend-Text", "conflict", 409, { code: "something_else", message: "Backend-Text" });
    expect(apiErrorMessage(unknown, t, "apiErrors", "fallback")).toBe("Backend-Text");
    expect(apiErrorMessage(new ApiError("", "backend", 500), t, "apiErrors", "fallback")).toBe("fallback");
    expect(apiErrorMessage("kaputt", t, "apiErrors", "fallback")).toBe("fallback");
  });

  it("ignoriert Codes mit fremden Zeichen", () => {
    expect(apiErrorCode(new ApiError("x", "backend", 400, { code: "../evil" }))).toBeNull();
    expect(apiErrorCode(new ApiError("x", "backend", 400, "nur Text"))).toBeNull();
  });

  it("erkennt ein 429 ohne Code (z. B. vom Proxy) als rate_limited", () => {
    expect(apiErrorCode(new ApiError("Too Many Requests", "backend", 429))).toBe("rate_limited");
    expect(apiErrorCode(new ApiError("x", "backend", 429, { code: "login_locked" }))).toBe("login_locked");
  });
});
