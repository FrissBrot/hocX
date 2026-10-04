// GENERATED FILE - do not edit by hand. Source of truth: i18n/locales.json (repo root).
// Regenerate with: python3 scripts/sync-i18n-config.py

export type Locale = "de" | "en" | "fr" | "it";

export interface LocaleInfo {
  /** Anzeigename in der aktuellen UI-Sprache (z.B. fuer Listen im Platform-Admin). */
  label: string;
  /** Name der Sprache in sich selbst, fuer den Language Selector ("Français", "Italiano"). */
  nativeLabel: string;
}

export const defaultLocale: Locale = "de";

export const localeCookieName = "hocx_locale";

export const locales: readonly Locale[] = ["de", "en", "fr", "it"] as const;

export const localeConfig: Record<Locale, LocaleInfo> = {
  "de": { label: "Deutsch", nativeLabel: "Deutsch" },
  "en": { label: "Englisch", nativeLabel: "English" },
  "fr": { label: "Franz\u00f6sisch", nativeLabel: "Fran\u00e7ais" },
  "it": { label: "Italienisch", nativeLabel: "Italiano" }
};

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (locales as readonly string[]).includes(value);
}
