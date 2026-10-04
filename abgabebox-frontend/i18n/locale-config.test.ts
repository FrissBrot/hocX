import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { defaultLocale, isLocale, localeConfig, locales } from "./locale-config.generated";

// Siehe frontend/i18n/locale-config.test.ts fuer die ausfuehrliche Begruendung (keine hart
// codierte Sprachliste - alle Tests leiten die zu pruefenden Sprachen dynamisch aus `locales`
// ab, generiert aus i18n/locales.json).

const MESSAGES_ROOT = path.join(__dirname, "..", "messages");

describe("zentrale Locale-Konfiguration (abgabebox-frontend)", () => {
  it("enthaelt mindestens eine Sprache und die Default-Locale ist selbst registriert", () => {
    expect(locales.length).toBeGreaterThan(0);
    expect(locales).toContain(defaultLocale);
  });

  it.each(locales)("isLocale erkennt die registrierte Locale '%s'", (code) => {
    expect(isLocale(code)).toBe(true);
  });

  it("isLocale lehnt eine unbekannte Locale ab", () => {
    expect(isLocale("xx")).toBe(false);
  });

  describe("Translation Catalogs", () => {
    it.each(locales)("hat ein messages/%s/-Verzeichnis mit mindestens einem Namespace", (code) => {
      const dir = path.join(MESSAGES_ROOT, code);
      expect(fs.existsSync(dir)).toBe(true);
      expect(fs.readdirSync(dir).filter((name) => name.endsWith(".json")).length).toBeGreaterThan(0);
    });

    it("jede Namespace-Datei ist gueltiges JSON mit identischer Key-Struktur ueber alle Locales", () => {
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
      for (const namespaceFile of fs.readdirSync(defaultDir).filter((n) => n.endsWith(".json"))) {
        const defaultKeys = Object.keys(flatten(JSON.parse(fs.readFileSync(path.join(defaultDir, namespaceFile), "utf-8")))).sort();
        for (const code of locales) {
          if (code === defaultLocale) continue;
          const filePath = path.join(MESSAGES_ROOT, code, namespaceFile);
          expect(fs.existsSync(filePath), `${code}/${namespaceFile}`).toBe(true);
          const keys = Object.keys(flatten(JSON.parse(fs.readFileSync(filePath, "utf-8")))).sort();
          expect(keys, `${code}/${namespaceFile}`).toEqual(defaultKeys);
        }
      }
    });
  });

  it("der Language Selector iteriert ueber `locales`/`localeConfig`, keine hart codierte Options-Liste (Erweiterbarkeit, Abschnitt 18)", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "components/language-select.tsx"), "utf-8");
    expect(source).toContain("locales.map");
    expect(source).toContain("localeConfig[code].nativeLabel");
    expect(source).not.toMatch(/<option value="(de|en|fr|it)"/);
  });
});
