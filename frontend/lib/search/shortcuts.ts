"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { findListSearchInput, focusListSearch } from "@/lib/search/list-search";
import { useShortcut } from "@/lib/keyboard/use-shortcut";

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
 * Tastenkürzel der App-Shell (Definitionen in lib/keyboard/registry.ts):
 * - global.search (Strg+K / ⌘K): globale Suche (überall, auch beim Tippen in einem Feld)
 * - global.listSearch (Strg+F / ⌘F): auf Seiten mit Liste ins Suchfeld der Liste; ist der Fokus
 *   schon dort (oder gibt es keine Liste), bleibt es bei der Browsersuche
 * - global.quickSearch («/» ausserhalb von Eingabefeldern): Suchfeld der Liste, sonst globale Suche
 * Seiten mit eigener Suche (Protokoll-Editor) binden `protocol.find` (Scope «page») - der
 * Dispatcher gibt ihr Vorrang. `data-own-find` bleibt als Markierung für Bereiche ohne eigene
 * Bindung erhalten (die Taste geht dann an den Browser).
 */
export function useGlobalSearchShortcuts(onOpenSearch: () => void, enabled = true): void {
  useShortcut(
    "global.search",
    () => {
      onOpenSearch();
    },
    { enabled }
  );
  useShortcut(
    "global.listSearch",
    () => {
      if (document.querySelector("[data-own-find]")) return false;
      const input = findListSearchInput();
      if (!input || document.activeElement === input) return false;
      focusListSearch(input);
    },
    { enabled }
  );
  useShortcut(
    "global.quickSearch",
    () => {
      const input = findListSearchInput();
      // In einem offenen Dialog ohne Suchfeld nichts tun (die Suche nicht über den Dialog legen)
      if (!input && document.querySelector('[role="dialog"]')) return false;
      if (input) focusListSearch(input);
      else onOpenSearch();
    },
    { enabled }
  );
}
