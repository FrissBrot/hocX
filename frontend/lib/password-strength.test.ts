import { describe, expect, it } from "vitest";

import { evaluatePassword, passwordStrengthLevel, personalTokens } from "@/lib/password-strength";

// Dieselben Beispiele wie backend/tests/test_password_policy.py: Anzeige und Prüfung im Backend
// müssen für jedes Passwort gleich urteilen.
const PERSONAL = ["Ben", "Beispiel", "Ben Beispiel", "ben@beispiel.ch", "Musterverein Seeland"];

const VECTORS: Array<[string, number, boolean, boolean]> = [
  ["", 0, false, false],
  ["kurz", 0, false, false],
  ["elfzeichen1", 0, false, false],
  ["zwoelfzeichen", 1, false, false],
  ["zwoelfzeichenA", 2, false, true],
  ["Zwoelfzeichen1", 2, false, true],
  ["sechzehnzeichenx", 2, false, true],
  ["Sechzehnzeichen1", 3, false, true],
  ["Sechzehnzeichen1!", 4, false, true],
  ["zwanzigzeichenlangxy", 3, false, true],
  ["Tanne-Kiesel-Wolke", 3, false, true],
  ["BenBeispiel-2026!", 1, true, false],
  ["Seeland-Wald-77x", 1, true, false],
  ["Passwort-Sicher-9", 1, true, false],
  ["mmm-Kiesel-Wolke7", 1, true, false],
  ["Fluss Ufer Möwe 42", 4, false, true],
  // SEC-AUTH-015: Folgen und Leetspeak aus Passwortlisten
  ["Kiesel-Wolke-12345", 1, true, false],
  ["Dr4gon-Kiesel-Wolke", 1, true, false],
  ["Wolke-Kiesel-98765", 1, true, false],
];

describe("evaluatePassword", () => {
  it.each(VECTORS)("%s → Stufe %i", (password, score, guessable, acceptable) => {
    const result = evaluatePassword(password, PERSONAL);
    expect([result.score, result.guessable, result.acceptable]).toEqual([score, guessable, acceptable]);
  });

  it("zerlegt Name, E-Mail und Organisation", () => {
    expect(personalTokens(PERSONAL)).toEqual(["beispiel", "ben", "musterverein", "seeland"]);
    expect(personalTokens(["Jo", null, ""])).toEqual([]);
  });

  it("wertet den lokalen Teil der E-Mail als persönlich", () => {
    expect(evaluatePassword("Kiesel.Mueller-2026", ["k.mueller@example.ch"]).guessable).toBe(true);
  });

  it("liefert die Checkliste und die Stufe", () => {
    const strength = evaluatePassword("Tanne-Kiesel-Wolke", PERSONAL);
    expect(strength.checks).toEqual({ minLength: true, mixedCase: true, numberOrSymbol: true, notGuessable: true });
    expect(passwordStrengthLevel(strength)).toBe("strong");
    expect(passwordStrengthLevel(evaluatePassword("kurz"))).toBe("tooShort");
    expect(passwordStrengthLevel(evaluatePassword(""))).toBe("empty");
    expect(passwordStrengthLevel(evaluatePassword("BenBeispiel-2026!", PERSONAL))).toBe("weak");
  });
});
