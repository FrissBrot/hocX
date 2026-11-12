import { describe, expect, it } from "vitest";

import { docsUrl } from "./docs";

describe("docsUrl", () => {
  it("baut die Adresse mit Abschnitt aus der Doku-Domain", () => {
    expect(docsUrl("abgabebox", "zeitfenster", "docs.example.org")).toBe("https://docs.example.org/benutzer/abgabebox/#zeitfenster");
    expect(docsUrl("abgabebox", undefined, "https://docs.example.org/")).toBe("https://docs.example.org/benutzer/abgabebox/");
  });

  it("liefert ohne Doku-Domain nichts", () => {
    expect(docsUrl("abgabebox", "x", null)).toBeNull();
    expect(docsUrl("abgabebox", "x", "  ")).toBeNull();
  });
});
