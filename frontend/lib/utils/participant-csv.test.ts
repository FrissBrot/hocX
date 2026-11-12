import { describe, expect, it } from "vitest";

import { CSV_TEMPLATE, parseParticipantCsv, splitCsv } from "./participant-csv";

describe("parseParticipantCsv", () => {
  it("liest die Spalten der Vereinssoftware mit Semikolon", () => {
    const preview = parseParticipantCsv("﻿Vorname;Nachname;Übername;Haupt-E-Mail\nAnna;Muster;;anna@example.org\n;;Kiki;\n");
    expect(preview.rows).toEqual([
      { display_name: "Anna Muster", first_name: "Anna", last_name: "Muster", email: "anna@example.org" },
      { display_name: "Kiki", first_name: null, last_name: null, email: null },
    ]);
    expect(preview.missingEmailColumn).toBe(false);
  });

  it("erkennt gängige Varianten wie «E-Mail» und Anführungszeichen wie das Backend", () => {
    const preview = parseParticipantCsv('Vorname,Nachname,E-Mail\n"Muster, Anna","van ""Dyk""",anna@example.org\n');
    expect(preview.rows).toEqual([{ display_name: 'Muster, Anna van "Dyk"', first_name: "Muster, Anna", last_name: 'van "Dyk"', email: "anna@example.org" }]);
  });

  it("meldet fehlende Spalten statt still ohne Daten zu importieren", () => {
    const preview = parseParticipantCsv("Vorname;Nachname;Adresse\nAnna;Muster;Weg 1\n");
    expect(preview.missingEmailColumn).toBe(true);
    expect(parseParticipantCsv("Spalte A;Spalte B\nx;y\n").rows).toEqual([]);
  });

  it("liest die eigene Vorlage", () => {
    expect(parseParticipantCsv(CSV_TEMPLATE).rows).toHaveLength(1);
  });

  it("zerlegt Zeilenumbrüche in Anführungszeichen nicht", () => {
    expect(splitCsv('a;"b\nc"\r\nd;e', ";")).toEqual([["a", "b\nc"], ["d", "e"]]);
  });
});
