import { afterEach, describe, expect, it } from "vitest";

import { ApiError, browserApiFetch } from "@/lib/api/client";
import { clientMessage, registerClientMessageTranslator } from "./client-messages";

describe("clientMessage (Audit MAIN-FE-010)", () => {
  afterEach(() => registerClientMessageTranslator(null));

  it("nutzt ohne registrierte Uebersetzung den Default-Katalog inkl. Platzhalter", () => {
    expect(clientMessage("offline")).toBe("Keine Internetverbindung");
    expect(clientMessage("saveFailedStatus", { status: 409 })).toBe("Speichern fehlgeschlagen (409)");
  });

  it("verwendet die registrierte Uebersetzung der aktuellen UI-Sprache", async () => {
    registerClientMessageTranslator((key, values) => `en:${key}${values ? JSON.stringify(values) : ""}`);
    expect(clientMessage("timeout")).toBe("en:timeout");

    const original = Object.getOwnPropertyDescriptor(window.navigator, "onLine");
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    try {
      await expect(browserApiFetch("/api/x")).rejects.toEqual(new ApiError("en:offline", "offline"));
    } finally {
      if (original) Object.defineProperty(window.navigator, "onLine", original);
      else delete (window.navigator as { onLine?: boolean }).onLine;
    }
  });
});
