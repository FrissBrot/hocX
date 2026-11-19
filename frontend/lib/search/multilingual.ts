import { locales } from "@/i18n/locale-config.generated";
import { buildStaticEntries } from "@/lib/search/static-entries";
import type { SessionInfo } from "@/types/api";

/**
 * Globale Suche (Ctrl+K) in allen Sprachen: «settings», «logs» oder «paramètres» finden die
 * Einträge auch, wenn hocX auf Deutsch läuft (und umgekehrt). Dafür werden Titel, Bereich und
 * Suchbegriffe derselben Einträge in den anderen Sprachen als zusätzliche Suchbegriffe angehängt.
 *
 * Die Texte der anderen Sprachen (nav.json, search.json) lädt die Suche erst beim Öffnen nach
 * (eigener kleiner Chunk) - die App lädt sie sonst nie.
 */
type Messages = Record<string, unknown>;
type Translator = ((key: string) => string) & { has: (key: string) => boolean };

function lookup(messages: Messages, key: string): string | undefined {
  let node: unknown = messages;
  for (const part of key.split(".")) {
    if (!node || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : undefined;
}

/** Wie next-intls t(): Schlüssel mit Punkten, has() für optionale Texte. Platzhalter ({count})
 * bleiben stehen - für Suchbegriffe unerheblich. */
export function translatorFor(messages: Messages): Translator {
  const t = ((key: string) => lookup(messages, key) ?? "") as Translator;
  t.has = (key: string) => lookup(messages, key) !== undefined;
  return t;
}

export type LanguageBundle = { nav: Messages; search: Messages };

let cache: Promise<LanguageBundle[]> | null = null;

/** Texte aller anderen Sprachen (einmal je Sitzung geladen). */
export function loadOtherLanguages(current: string): Promise<LanguageBundle[]> {
  cache ??= Promise.all(
    locales
      .filter((locale) => locale !== current)
      .map(async (locale) => ({
        nav: (await import(`@/messages/${locale}/nav.json`)).default as Messages,
        search: (await import(`@/messages/${locale}/search.json`)).default as Messages,
      }))
  ).catch(() => {
    cache = null; // nächster Versuch beim nächsten Öffnen; die Suche läuft ohne weiter
    return [];
  });
  return cache;
}

/** Zusätzliche Suchbegriffe je Eintrag (id) aus den anderen Sprachen. Dieselbe Rechte-Prüfung
 * wie die eigentlichen Einträge (buildStaticEntries/buildNav). */
export function crossLanguageKeywords(session: SessionInfo | null, bundles: LanguageBundle[]): Map<string, string> {
  const extra = new Map<string, string[]>();
  for (const bundle of bundles) {
    for (const entry of buildStaticEntries(session, translatorFor(bundle.nav), translatorFor(bundle.search))) {
      const words = [entry.label, entry.sublabel, entry.keywords].filter(Boolean) as string[];
      extra.set(entry.id, [...(extra.get(entry.id) ?? []), ...words]);
    }
  }
  return new Map([...extra].map(([id, words]) => [id, words.join(" ")]));
}
