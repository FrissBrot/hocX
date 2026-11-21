import { describe, expect, it } from "vitest";

import { countryName } from "./country";

describe("countryName", () => {
  it("übersetzt den Ländercode in die UI-Sprache", () => {
    expect(countryName("CH", "de")).toBe("Schweiz");
    expect(countryName("CH", "fr")).toBe("Suisse");
    expect(countryName("DE", "en")).toBe("Germany");
  });

  it("liefert null für fehlende oder ungültige Codes", () => {
    expect(countryName(null, "de")).toBeNull();
    expect(countryName("", "de")).toBeNull();
    expect(countryName("che", "de")).toBeNull();
  });
});
