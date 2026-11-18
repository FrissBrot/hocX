"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { findListSearchInput, focusListSearch, isEditableTarget } from "@/lib/search/list-search";

/** ⌘ auf Apple-Geräten, sonst Ctrl - nur für die Anzeige der Tastenkürzel. */
/** Apple-Gerät (Mac, iPhone, iPad): Kürzel mit ⌘ statt Ctrl/Strg. Nur im Browser aufrufen. */
export function isApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? "";
  return /mac|iphone|ipad/i.test(platform);
}

/** true auf Apple-Geräten; erst nach dem Mounten bestimmt (Server-Render ohne Gerät). */
export function useIsApple(): boolean {
  const [apple, setApple] = useState(false);
  useEffect(() => setApple(isApplePlatform()), []);
  return apple;
}

/** Name der Steuerungstaste: «⌘» auf Apple-Geräten, sonst «Strg»/«Ctrl» je nach Sprache. */
export function useModifierLabel(): string {
  const t = useTranslations("common.keys");
  return useIsApple() ? "⌘" : t("ctrl");
}

/**
 * Beschriftung eines Tastenkürzels mit Steuerungstaste - überall statt festem «Ctrl+…»/«Strg+…»
 * (DESIGN.md Abschnitt 9): Apple «⌘K», sonst «Strg+K» bzw. «Ctrl+K».
 */
export function useShortcutLabel(): (key: string) => string {
  const t = useTranslations("common.keys");
  const apple = useIsApple();
  return (key: string) => (apple ? `⌘${key}` : `${t("ctrl")}+${key}`);
}

/**
 * Tastenkürzel der App-Shell:
 * - Ctrl+K / ⌘K: globale Suche (überall, auch beim Tippen in einem Feld)
 * - Ctrl+F / ⌘F: auf Seiten mit Liste ins Suchfeld der Liste; ist der Fokus schon dort (oder
 *   gibt es keine Liste), bleibt es bei der Browsersuche
 * - «/» ausserhalb von Eingabefeldern: Suchfeld der Liste, sonst globale Suche
 * Seiten mit eigener Suche (Protokoll-Editor) fangen Ctrl+F selbst ab (preventDefault); das hat
 * Vorrang.
 */
export function useGlobalSearchShortcuts(onOpenSearch: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing) return;
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (mod && !event.altKey && !event.shiftKey && key === "k") {
        event.preventDefault();
        onOpenSearch();
        return;
      }
      if (mod && !event.altKey && !event.shiftKey && key === "f") {
        if (document.querySelector("[data-own-find]")) return;
        const input = findListSearchInput();
        if (!input || document.activeElement === input) return;
        event.preventDefault();
        focusListSearch(input);
        return;
      }
      if (key === "/" && !mod && !event.altKey && !isEditableTarget(event.target)) {
        const input = findListSearchInput();
        // In einem offenen Dialog ohne Suchfeld nichts tun (die Suche nicht über den Dialog legen)
        if (!input && document.querySelector('[role="dialog"]')) return;
        event.preventDefault();
        if (input) focusListSearch(input);
        else onOpenSearch();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onOpenSearch, enabled]);
}
