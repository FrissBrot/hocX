import fs from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

// Fehler gehören in einen Toast mit Typ "error" (design/DESIGN.md, Abschnitt 4). Ohne Typ
// nimmt useToast "info": der Fehler beim Annehmen nachverfolgter Änderungen, beim Umschalten
// der Änderungsverfolgung oder beim Verknüpfen einer Pendenz sah aus wie ein blauer Hinweis.
const FILES = [
  "components/protocol/protocol-editor.tsx",
  "components/protocol/focused-element-editor.tsx",
  "components/protocol/session-panel.tsx",
  "components/mobile/mobile-protocol-editor.tsx",
];

it("shows caught errors in the protocol editors as error toasts", () => {
  const offenders: string[] = [];
  for (const file of FILES) {
    const source = fs.readFileSync(path.join(__dirname, "..", "..", file), "utf-8");
    source.split("\n").forEach((line, index) => {
      // showToast(<x>.message) ohne zweiten Parameter
      if (/showToast\(\s*\w+\.message\s*\)/.test(line)) offenders.push(`${file}:${index + 1}`);
    });
  }
  expect(offenders).toEqual([]);
});
