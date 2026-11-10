import { describe, expect, it } from "vitest";

import { findLinks } from "./autolink";

const texts = (text: string) => findLinks(text).map((link) => [text.slice(link.from, link.to), link.href]);

describe("findLinks", () => {
  it("erkennt URLs und E-Mail-Adressen", () => {
    expect(texts("Mailadresse: scharleitung@example.ch")).toEqual([["scharleitung@example.ch", "mailto:scharleitung@example.ch"]]);
    expect(texts("Link OneDrive: https://example.sharepoint.com/:f:/g/EuD1h7d_Pcrt-9Dk?e=1")).toEqual([
      ["https://example.sharepoint.com/:f:/g/EuD1h7d_Pcrt-9Dk?e=1", "https://example.sharepoint.com/:f:/g/EuD1h7d_Pcrt-9Dk?e=1"],
    ]);
  });

  it("schneidet Satzzeichen ab und ergänzt https bei www", () => {
    expect(texts("Siehe www.example.ch.")).toEqual([["www.example.ch", "https://www.example.ch"]]);
    expect(texts("(mehr: https://de.wikipedia.org/wiki/Sachseln_(OW))")).toEqual([
      ["https://de.wikipedia.org/wiki/Sachseln_(OW)", "https://de.wikipedia.org/wiki/Sachseln_(OW)"],
    ]);
  });

  it("lässt gewöhnlichen Text in Ruhe", () => {
    expect(findLinks("Passwort: jw$ach3ln-1958, Version 1.2.3, javascript:alert(1)")).toEqual([]);
  });
});
