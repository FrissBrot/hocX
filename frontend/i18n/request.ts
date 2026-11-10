import fs from "node:fs";
import path from "node:path";
import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { defaultLocale, isLocale, localeCookieName, type Locale } from "@/i18n/locale-config.generated";

// Nicht auf einen festen Satz von Sprachen verdrahtet: die Katalog-Namespaces (common, nav,
// participants, ...) werden pro Locale dynamisch aus messages/<locale>/*.json eingelesen, nicht
// einzeln importiert - eine neue Namespace-Datei wird ohne Code-Aenderung hier automatisch Teil
// des Katalogs. Welche LOCALES ueberhaupt existieren, kommt ausschliesslich aus
// locale-config.generated.ts (siehe i18n/locales.json, die eigentliche Source of Truth).
const MESSAGES_ROOT = path.join(process.cwd(), "messages");

function loadMessages(locale: Locale): Record<string, unknown> {
  const dir = path.join(MESSAGES_ROOT, locale);
  const messages: Record<string, unknown> = {};
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) {
      continue;
    }
    const namespace = entry.name.slice(0, -".json".length);
    messages[namespace] = JSON.parse(fs.readFileSync(path.join(dir, entry.name), "utf-8"));
  }
  return messages;
}

// Nur die Haupt-Subtag auswerten (z.B. "fr" aus "fr-CH;q=0.9") - Regionen (CH/FR/...) haben
// hier aktuell keine eigenen Kataloge.
function resolveFromAcceptLanguage(header: string | null): Locale | null {
  if (!header) {
    return null;
  }
  const candidates = header
    .split(",")
    .map((part) => part.split(";")[0]?.trim().split("-")[0]?.toLowerCase())
    .filter((value): value is string => !!value);
  for (const candidate of candidates) {
    if (isLocale(candidate)) {
      return candidate;
    }
  }
  return null;
}

// Prioritaet (siehe CLAUDE.md, Abschnitt i18n): 1. explizit gespeicherte Benutzerpraeferenz,
// 2. persistenter Locale-Cookie, 3. unterstuetzte Browser-Sprache, 4. Default-Locale. Die
// gespeicherte Benutzerpraeferenz (preferred_language) wird vom Backend bei jedem Login und bei
// jedem Session-Abruf (/api/auth/session) in genau diesen Cookie gespiegelt (siehe
// issue_locale_cookie in backend/app/core/security.py) - Stufe 1 und 2 fallen fuer den
// Server-Request dadurch zusammen, ohne dass hier ein zusaetzlicher Netzwerk-Request noetig
// waere. Eine unbekannte/nicht unterstuetzte Locale im Cookie faellt einfach durch zu Stufe 3.
export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(localeCookieName)?.value;

  let locale: Locale;
  if (isLocale(cookieLocale)) {
    locale = cookieLocale;
  } else {
    const headerList = await headers();
    locale = resolveFromAcceptLanguage(headerList.get("accept-language")) ?? defaultLocale;
  }

  return {
    locale,
    messages: loadMessages(locale),
  };
});
