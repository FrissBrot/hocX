import fs from "node:fs";
import path from "node:path";
import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { defaultLocale, isLocale, localeCookieName, type Locale } from "@/i18n/locale-config.generated";

// Oeffentliche, anonyme Upload-Seite: es gibt keine Benutzerpraeferenz zum Abgleichen (kein
// Login) - Prioritaet ist daher nur Cookie (gesetzt vom Language Selector, siehe
// components/language-select.tsx) > Browser-Sprache > Default. Namespace-Dateien werden wie im
// Hauptfrontend dynamisch aus messages/<locale>/*.json eingelesen (siehe dortiges
// i18n/request.ts fuer die ausfuehrliche Begruendung).
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
