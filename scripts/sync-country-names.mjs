#!/usr/bin/env node
// Ländernamen für Mails aus dem Backend (Anmeldehinweise «neues Gerät»/verdächtige Anmeldung).
//
//   node scripts/sync-country-names.mjs           # erzeugen
//   node scripts/sync-country-names.mjs --check   # nur prüfen (Exit 1 bei Abweichung)
//
// Quelle sind die CLDR-Daten von Node (Intl.DisplayNames, type "region") für alle Sprachen aus
// i18n/locales.json - dieselben Namen, die das Frontend für «Angemeldete Geräte» per
// Intl.DisplayNames im Browser zeigt. Das Backend hat kein ICU, darum eine generierte Kopie unter
// backend/app/core/country_names_generated.json. Nie von Hand bearbeiten.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(root, "backend/app/core/country_names_generated.json");
const locales = Object.keys(JSON.parse(fs.readFileSync(path.join(root, "i18n/locales.json"), "utf-8")).locales);

const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
// Nur offizielle Ländercodes (ISO 3166-1 alpha-2); reservierte/benutzerdefinierte Codes fallen weg.
const english = new Intl.DisplayNames(["en"], { type: "region", fallback: "none" });
const codes = [];
for (const a of letters) {
  for (const b of letters) {
    const code = a + b;
    if (["EU", "EZ", "UN", "QO", "ZZ"].includes(code) || code.startsWith("X") && code !== "XK") continue;
    if (english.of(code)) codes.push(code);
  }
}

const result = {};
for (const locale of locales) {
  const names = new Intl.DisplayNames([locale], { type: "region", fallback: "none" });
  result[locale] = Object.fromEntries(codes.map((code) => [code, names.of(code)]).filter(([, name]) => name));
}
const content = JSON.stringify(result, null, 1) + "\n";

if (process.argv.includes("--check")) {
  const current = fs.existsSync(target) ? fs.readFileSync(target, "utf-8") : "";
  if (current !== content) {
    console.error("backend/app/core/country_names_generated.json veraltet (node scripts/sync-country-names.mjs)");
    process.exit(1);
  }
  console.log("Ländernamen: ok");
} else {
  fs.writeFileSync(target, content);
  console.log(`${path.relative(root, target)}: ${codes.length} Länder, ${locales.length} Sprachen`);
}
