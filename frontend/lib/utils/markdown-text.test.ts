import { describe, expect, it } from "vitest";

import { markdownToPlainText } from "./markdown-text";

describe("markdownToPlainText", () => {
  it("entfernt Formatierung und verbindet Zeilen", () => {
    expect(markdownToPlainText("**Treffpunkt** beim *Pfadiheim*\n\n- Lunch\n- Wanderschuhe")).toBe("Treffpunkt beim Pfadiheim · Lunch · Wanderschuhe");
  });

  it("behält Linktext und Klartext", () => {
    expect(markdownToPlainText("## Programm\n[Karte](https://example.org) und 1\\. Teil")).toBe("Programm · Karte und 1. Teil");
  });

  it("löst Zahl-Entitäten neben Auszeichnungen auf", () => {
    expect(markdownToPlainText("A **B!**&#67; und &#120;*!y*")).toBe("A B!C und x!y");
    expect(markdownToPlainText("Gut **!**&#xE4;ndern")).toBe("Gut !ändern");
  });

  it("leer bleibt leer", () => {
    expect(markdownToPlainText(null)).toBe("");
    expect(markdownToPlainText("  \n ")).toBe("");
  });
});

