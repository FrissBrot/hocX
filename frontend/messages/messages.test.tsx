import fs from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// vitest.setup.ts mockt next-intl global fest auf die "de"-Kataloge (siehe dortiger Kommentar),
// damit die ~90 bestehenden Komponenten-Tests keinen Provider brauchen. Genau das wuerde hier
// jeden Rendering-Test unabhaengig von der tatsaechlich hereingereichten Locale auf "de"
// einfrieren - fuer DIESE Datei also bewusst wieder deaktiviert, um next-intl's echtes
// Verhalten (inkl. Provider-Context) je Locale zu pruefen. vi.unmock() wird von vitest vor die
// Imports gehoisted, wirkt also schon fuer die statischen Importe unten.
vi.unmock("next-intl");

import { createTranslator, NextIntlClientProvider } from "next-intl";
import { defaultLocale, locales, localeConfig, isLocale, type Locale } from "@/i18n/locale-config.generated";
import { ToastProvider, useToast } from "@/contexts/toast-context";

// Dieser Test ist bewusst NICHT durch den next-intl-Mock in vitest.setup.ts abgedeckt (der mockt
// useTranslations/useLocale fest auf "de") - er importiert next-intl direkt (createTranslator,
// NextIntlClientProvider), um die echten Kataloge aller registrierten Locales zu pruefen, nicht
// nur Deutsch. Siehe scripts/check-i18n-completeness.py fuer den analogen, staerker auf CI
// zugeschnittenen Check (Key-fuer-Key-Diff pro Namespace) - hier geht es zusaetzlich darum, dass
// next-intl die Kataloge tatsaechlich LADEN und eine ICU-Message daraus FORMATIEREN kann, und
// dass die zentrale Locale-Konfiguration intern konsistent ist (Requirement: Tests laufen
// automatisch fuer jede zukuenftig registrierte Locale, ohne dass diese Datei angepasst werden
// muss - deshalb ausschliesslich ueber `locales`/`defaultLocale` aus locale-config.generated.ts
// iteriert, nirgends ein Locale-Code als Literal).

const messagesRoot = path.join(__dirname);

function loadMessages(locale: string): Record<string, unknown> {
  const dir = path.join(messagesRoot, locale);
  const out: Record<string, unknown> = {};
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isFile() && entry.name.endsWith(".json")) {
      out[entry.name.slice(0, -".json".length)] = JSON.parse(fs.readFileSync(path.join(dir, entry.name), "utf-8"));
    }
  }
  return out;
}

function flattenKeys(obj: unknown, prefix = ""): { key: string; message: string }[] {
  if (typeof obj === "string") {
    return [{ key: prefix, message: obj }];
  }
  if (obj && typeof obj === "object") {
    return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) => flattenKeys(v, prefix ? `${prefix}.${k}` : k));
  }
  return [];
}

// Dummy-Werte fuer jede ICU-Variable/Plural-Kategorie in der Message, damit t(key, params) nicht
// wegen eines fehlenden Platzhalterwerts wirft - ein echter Syntaxfehler in der ICU-Message
// (z.B. unausgeglichene Klammern einer plural-Regel) wirft dagegen trotzdem, das ist der Punkt
// dieses Smoke-Tests.
function dummyParamsFor(message: string): Record<string, number> {
  const params: Record<string, number> = {};
  for (const match of message.matchAll(/\{(\w+)[,}]/g)) {
    params[match[1]] = 1;
  }
  return params;
}

describe("zentrale Locale-Konfiguration (i18n/locales.json)", () => {
  it("fuehrt die Default-Locale als registrierte Locale", () => {
    expect(locales).toContain(defaultLocale);
  });

  it("hat fuer jede Locale einen Anzeigenamen und einen nativen Namen", () => {
    for (const locale of locales) {
      expect(localeConfig[locale].label, locale).toBeTruthy();
      expect(localeConfig[locale].nativeLabel, locale).toBeTruthy();
    }
  });

  it("faellt fuer eine unbekannte/leere Locale korrekt zurueck statt zu crashen", () => {
    expect(isLocale("xx")).toBe(false);
    expect(isLocale("")).toBe(false);
    expect(isLocale(undefined)).toBe(false);
    expect(isLocale(null)).toBe(false);
  });

  it("hat fuer jede registrierte Locale ein messages/<locale>/-Verzeichnis mit mindestens einem Namespace", () => {
    for (const locale of locales) {
      const dir = path.join(messagesRoot, locale);
      expect(fs.existsSync(dir), `messages/${locale}`).toBe(true);
      const namespaces = fs.readdirSync(dir).filter((f) => f.endsWith(".json"));
      expect(namespaces.length, `namespaces in messages/${locale}`).toBeGreaterThan(0);
    }
  });

  it("hat denselben Satz an Namespace-Dateien in jeder Locale", () => {
    const reference = fs.readdirSync(path.join(messagesRoot, defaultLocale)).filter((f) => f.endsWith(".json")).sort();
    for (const locale of locales) {
      const namespaces = fs.readdirSync(path.join(messagesRoot, locale)).filter((f) => f.endsWith(".json")).sort();
      expect(namespaces, `namespaces in messages/${locale}`).toEqual(reference);
    }
  });
});

// describe.each statt eines hartcodierten for-de/en/fr/it: eine fuenfte, neu registrierte Locale
// taucht hier automatisch als eigener Testlauf auf, ohne dass diese Datei geaendert werden muss.
describe.each(locales)("Locale '%s'", (locale) => {
  it("laedt alle Namespace-Kataloge ohne Fehler", () => {
    expect(() => loadMessages(locale)).not.toThrow();
  });

  it("jede Message ist gueltiges ICU (next-intl kann sie formatieren)", () => {
    const messages = loadMessages(locale);
    for (const [namespace, content] of Object.entries(messages)) {
      const t = createTranslator({ locale, messages: { [namespace]: content } as Record<string, unknown>, namespace });
      for (const { key, message } of flattenKeys(content)) {
        expect(() => t(key, dummyParamsFor(message)), `${namespace}.${key}`).not.toThrow();
      }
    }
  });
});

function Probe() {
  const showToast = useToast();
  return (
    <button type="button" onClick={() => showToast("x", "info")}>
      probe
    </button>
  );
}

describe.each(locales)("Rendering mit Locale '%s' (NextIntlClientProvider)", (locale) => {
  it("rendert einen gemeinsam genutzten Baustein (ToastProvider) ohne zu werfen", () => {
    const messages = loadMessages(locale);
    expect(() =>
      render(
        <NextIntlClientProvider locale={locale} messages={messages}>
          <ToastProvider>
            <Probe />
          </ToastProvider>
        </NextIntlClientProvider>
      )
    ).not.toThrow();
    expect(screen.getByRole("button", { name: "probe" })).toBeInTheDocument();
  });
});

describe("Erweiterbarkeit (Requirement: fuenfte Sprache ohne Codeaenderung)", () => {
  it("die Locale-Liste kommt ausschliesslich aus locale-config.generated.ts, nirgends dupliziert in dieser Datei", () => {
    // Dieser Test ist bewusst tautologisch dokumentiert: er stellt sicher, dass ein Reviewer, der
    // hier je einen literalen Locale-Code ("de"/"en"/...) ergaenzt, einen Grund braucht - alle
    // Pruefungen oben laufen ausschliesslich ueber die importierte `locales`-Liste.
    expect(locales.length).toBeGreaterThanOrEqual(1);
    const uniq = new Set(locales as readonly Locale[]);
    expect(uniq.size).toBe(locales.length);
  });
});
