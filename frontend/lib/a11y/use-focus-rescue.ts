"use client";

import { useEffect } from "react";

import { getTabbables, MAIN_CONTENT_ID } from "./focus";

/**
 * Fängt verlorenen Tastaturfokus auf (WCAG 2.4.3): Wird das fokussierte Element entfernt - die
 * gelöschte Zeile, ein Knopf, der nach dem Speichern verschwindet, die alte Seite nach einem
 * Seitenwechsel -, stünde der Fokus auf <body> und der nächste Tab begänne oben auf der Seite.
 *
 * Stattdessen: nächster noch vorhandener Vorfahr des alten Elements. Liegt der innerhalb des
 * Hauptinhalts, bekommt dessen erstes Tab-Ziel den Fokus (Nachbarzeile, Liste), sonst der
 * Hauptinhalt selbst (#main-content, tabIndex=-1). Einmal in der App-Shell montieren.
 */
export function useFocusRescue(): void {
  useEffect(() => {
    let ancestors: Element[] = [];
    let last: Element | null = null;

    function remember(event: FocusEvent) {
      const target = event.target;
      if (!(target instanceof Element) || target === document.body) return;
      last = target;
      ancestors = [];
      for (let node = target.parentElement; node && node !== document.body; node = node.parentElement) ancestors.push(node);
    }

    function rescue() {
      const active = document.activeElement;
      if (!last || last.isConnected || (active && active !== document.body)) return;
      const main = document.getElementById(MAIN_CONTENT_ID);
      const survivor = ancestors.find((node) => node.isConnected) ?? null;
      last = null;
      const inDialog = survivor?.closest('[role="dialog"], [role="alertdialog"]');
      if (survivor instanceof HTMLElement && survivor !== main && ((main && main.contains(survivor)) || (inDialog && inDialog !== survivor))) {
        const next = getTabbables(survivor)[0];
        if (next) {
          next.focus({ preventScroll: true });
          return;
        }
      }
      // In einem offenen Dialog bleibt der Fokus im Dialog (dessen Fokusfalle übernimmt beim
      // nächsten Tab), sonst der Hauptinhalt.
      const dialog = survivor?.closest<HTMLElement>('[role="dialog"], [role="alertdialog"]');
      if (dialog && dialog.tabIndex >= -1 && dialog.hasAttribute("tabindex")) dialog.focus({ preventScroll: true });
      else main?.focus({ preventScroll: true });
    }

    // Einen Frame warten: Dialoge geben den Fokus in ihrem Effekt-Cleanup selbst zurück.
    let frame = 0;
    const observer = new MutationObserver(() => {
      if (!last || last.isConnected || frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        rescue();
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("focusin", remember);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      document.removeEventListener("focusin", remember);
    };
  }, []);
}
