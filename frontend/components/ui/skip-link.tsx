"use client";

import { useTranslations } from "next-intl";

import { MAIN_CONTENT_ID } from "@/lib/a11y/focus";

/**
 * «Zum Inhalt springen»: erster Tab-Halt jeder Seite mit Navigation (WCAG 2.4.1). Unsichtbar,
 * bis er den Tastaturfokus hat; springt über Seitenleiste und Kopfzeile in den Hauptinhalt.
 */
export function SkipLink() {
  const t = useTranslations("common.keyboard");
  return (
    <a
      className="skip-link"
      href={`#${MAIN_CONTENT_ID}`}
      onClick={(event) => {
        // Hash-Navigation fokussiert in Safari nicht zuverlässig - selbst fokussieren
        const main = document.getElementById(MAIN_CONTENT_ID);
        if (!main) return;
        event.preventDefault();
        main.focus();
        main.scrollIntoView({ block: "start" });
      }}
    >
      {t("skipToContent")}
    </a>
  );
}
