"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { isLocale, localeCookieName, localeConfig, locales } from "@/i18n/locale-config.generated";

const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

// Sprachwahl der oeffentlichen Website: Besucher haben keine Session/Benutzerpraeferenz, deshalb
// wird direkt der Locale-Cookie gesetzt, den i18n/request.ts serverseitig auswertet (Stufe 2 der
// Prioritaet), und die Seite neu gerendert.
export function WebsiteLanguageSwitcher() {
  const t = useTranslations("website.nav");
  const locale = useLocale();
  const router = useRouter();

  function onChange(value: string) {
    if (!isLocale(value) || value === locale) {
      return;
    }
    document.cookie = `${localeCookieName}=${value}; path=/; max-age=${ONE_YEAR_SECONDS}; samesite=lax`;
    router.refresh();
  }

  return (
    <span className="ws-language">
      <select aria-label={t("language")} value={locale} onChange={(event) => onChange(event.target.value)}>
        {locales.map((code) => (
          <option key={code} value={code}>
            {localeConfig[code].nativeLabel}
          </option>
        ))}
      </select>
    </span>
  );
}
