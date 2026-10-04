"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { locales, localeConfig, localeCookieName, type Locale } from "@/i18n/locale-config.generated";

// Oeffentliche, anonyme Seite ohne Login - die Sprachwahl wirkt daher rein ueber den
// Locale-Cookie (kein preferred_language zum Abgleichen, siehe i18n/request.ts). router.refresh()
// laesst den Server die Seite mit dem neuen Cookie sofort neu rendern, ohne vollen Reload.
export function LanguageSelect({ currentLocale }: { currentLocale: string }) {
  const t = useTranslations("abgabebox.language");
  const router = useRouter();

  function changeLocale(next: Locale) {
    const maxAgeSeconds = 60 * 60 * 24 * 365;
    document.cookie = `${localeCookieName}=${next}; path=/; max-age=${maxAgeSeconds}; samesite=lax`;
    router.refresh();
  }

  return (
    <label className="page-header-language">
      <span className="sr-only">{t("label")}</span>
      <select value={currentLocale} onChange={(event) => changeLocale(event.target.value as Locale)}>
        {locales.map((code) => (
          <option key={code} value={code}>
            {localeConfig[code].nativeLabel}
          </option>
        ))}
      </select>
    </label>
  );
}
