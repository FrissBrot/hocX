"use client";

import { useEffect, useState } from "react";

import { findListSearchInput, focusListSearch, isEditableTarget } from "@/lib/search/list-search";

/** ⌘ auf Apple-Geräten, sonst Ctrl - nur für die Anzeige der Tastenkürzel. */
export function useModifierLabel(): string {
  const [label, setLabel] = useState("Ctrl"); // i18n-ok: Tastenname
  useEffect(() => {
    const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ?? navigator.platform ?? "";
    if (/mac|iphone|ipad/i.test(platform)) setLabel("⌘");
  }, []);
  return label;
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
