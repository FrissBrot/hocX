import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { defaultLocale, isLocale, localeConfig, locales } from "./locale-config.generated";

// Alle Tests leiten die zu pruefenden Sprachen dynamisch aus `locales` ab (generiert aus
// i18n/locales.json, siehe scripts/sync-i18n-config.py) - KEINE hart codierte Liste wie
// ["de", "en", "fr", "it"]. Eine neu registrierte Sprache wird von diesen Tests automatisch
// mitgeprueft, ohne dass diese Datei angepasst werden muss (siehe CLAUDE.md, Abschnitt i18n).

const MESSAGES_ROOT = path.join(__dirname, "..", "messages");

describe("zentrale Locale-Konfiguration", () => {
  it("enthaelt mindestens eine Sprache und die Default-Locale ist selbst registriert", () => {
    expect(locales.length).toBeGreaterThan(0);
    expect(locales).toContain(defaultLocale);
  });

  it("hat fuer jede registrierte Locale einen Eintrag mit Anzeigename und nativem Namen", () => {
    for (const code of locales) {
      expect(localeConfig[code]).toBeDefined();
      expect(localeConfig[code].label.length).toBeGreaterThan(0);
      expect(localeConfig[code].nativeLabel.length).toBeGreaterThan(0);
    }
  });

  it("hat keine doppelten Locale-Codes", () => {
    expect(new Set(locales).size).toBe(locales.length);
  });

  describe("isLocale", () => {
    it.each(locales)("erkennt die registrierte Locale '%s'", (code) => {
      expect(isLocale(code)).toBe(true);
    });

    it("lehnt eine unbekannte/nicht registrierte Locale ab, ohne zu werfen", () => {
      expect(isLocale("xx")).toBe(false);
      expect(isLocale(undefined)).toBe(false);
      expect(isLocale(null)).toBe(false);
      expect(isLocale("")).toBe(false);
    });
  });

  describe("Translation Catalogs (messages/<locale>/*.json)", () => {
    it.each(locales)("hat ein messages/%s/-Verzeichnis mit mindestens einem Namespace", (code) => {
      const dir = path.join(MESSAGES_ROOT, code);
      expect(fs.existsSync(dir)).toBe(true);
      const namespaces = fs.readdirSync(dir).filter((name) => name.endsWith(".json"));
      expect(namespaces.length).toBeGreaterThan(0);
    });

    it("jede Locale hat denselben Satz an Namespace-Dateien wie die Default-Locale", () => {
      const defaultNamespaces = new Set(
        fs.readdirSync(path.join(MESSAGES_ROOT, defaultLocale)).filter((name) => name.endsWith(".json"))
      );
      for (const code of locales) {
        const namespaces = new Set(
          fs.readdirSync(path.join(MESSAGES_ROOT, code)).filter((name) => name.endsWith(".json"))
        );
        expect(new Set([...namespaces].sort()), `Namespaces fuer '${code}'`).toEqual(
          new Set([...defaultNamespaces].sort())
        );
      }
    });

    it("jede Namespace-Datei ist gueltiges JSON mit identischer, vollstaendiger Key-Struktur ueber alle Locales", () => {
      function flatten(value: unknown, prefix = ""): Record<string, unknown> {
        if (value && typeof value === "object" && !Array.isArray(value)) {
          return Object.entries(value as Record<string, unknown>).reduce<Record<string, unknown>>((acc, [key, v]) => {
            Object.assign(acc, flatten(v, prefix ? `${prefix}.${key}` : key));
            return acc;
          }, {});
        }
        return { [prefix]: value };
      }

      const defaultDir = path.join(MESSAGES_ROOT, defaultLocale);
      const namespaceFiles = fs.readdirSync(defaultDir).filter((name) => name.endsWith(".json"));

      for (const namespaceFile of namespaceFiles) {
        const defaultContent = JSON.parse(fs.readFileSync(path.join(defaultDir, namespaceFile), "utf-8"));
        const defaultKeys = Object.keys(flatten(defaultContent)).sort();

        for (const code of locales) {
          if (code === defaultLocale) continue;
          const filePath = path.join(MESSAGES_ROOT, code, namespaceFile);
          expect(fs.existsSync(filePath), `${code}/${namespaceFile} sollte existieren`).toBe(true);
          const content = JSON.parse(fs.readFileSync(filePath, "utf-8"));
          const keys = Object.keys(flatten(content)).sort();
          expect(keys, `Key-Struktur von ${code}/${namespaceFile} vs. ${defaultLocale}/${namespaceFile}`).toEqual(
            defaultKeys
          );
        }
      }
    });
  });

  describe("Erweiterbarkeit (Abschnitt 18: eine fuenfte Sprache ohne Code-Aenderung)", () => {
    it("der Language Selector (profile-modal.tsx) iteriert ueber `locales`/`localeConfig`, keine hart codierte Options-Liste", () => {
      const source = fs.readFileSync(path.join(__dirname, "..", "components/ui/profile-modal.tsx"), "utf-8");
      expect(source).toContain("locales.map");
      expect(source).toContain("localeConfig[code].nativeLabel");
      // Keine hart codierten <option value="de">-artigen Eintraege mehr.
      expect(source).not.toMatch(/<option value="(de|en|fr|it)"/);
    });

    // abgabebox-frontend ist ein separates Deployment/Docker-Image (siehe
    // frontend/lib/api/client.ts-Kommentar zur bewussten Trennung) - dessen Quellcode liegt
    // nicht im Build-Kontext dieses Containers und wird daher in dessen EIGENER Testsuite
    // gegengeprueft (siehe abgabebox-frontend/components/language-select.tsx), nicht hier.
  });
});
