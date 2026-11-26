"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { MAIN_CONTENT_ID } from "@/lib/a11y/focus";

// Gleicher Umschaltpunkt wie die 900/901-px-Breakpoints in globals.css (design/DESIGN.md
// Abschnitt 2) - bis einschliesslich 900 px gilt die Mobile-Oberflaeche.
export const MOBILE_MEDIA_QUERY = "(max-width: 900px)";

type ViewportState = {
  /** Shell (Navigation/Rahmen): folgt der Breite sofort. */
  isMobile: boolean;
  /** Seitenvariante (ResponsiveView): wechselt erst, wenn nichts Ungespeichertes offen ist. */
  contentMobile: boolean;
  /** Schiebt den Variantenwechsel auf, bis die zurueckgegebene Freigabe aufgerufen wird. */
  hold: () => () => void;
  /** 1, wenn die erste Korrektur nach dem Laden die Ansicht gewechselt hat (sonst 0). */
  epoch: number;
};

const ViewportContext = createContext<ViewportState>({ isMobile: false, contentMobile: false, hold: () => () => {}, epoch: 0 });

// Eingabefelder, in denen getippt wird. Knoepfe, Checkboxen und Radios zaehlen nicht: ihr Zustand
// ist mit dem Klick schon gesetzt, ein Fokus darauf soll den Wechsel nicht aufhalten.
const NON_TEXT_INPUTS = new Set(["button", "submit", "reset", "checkbox", "radio", "range", "color", "file", "image", "hidden"]);

/** true, solange der Fokus in einem Eingabefeld des Seiteninhalts (#main-content) steht. */
export function isEditingPageContent(): boolean {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement)) return false;
  if (!document.getElementById(MAIN_CONTENT_ID)?.contains(active)) return false;
  if (active.isContentEditable || active instanceof HTMLTextAreaElement || active instanceof HTMLSelectElement) return true;
  return active instanceof HTMLInputElement && !NON_TEXT_INPUTS.has(active.type);
}

/**
 * Liefert, ob die Mobile-Oberflaeche aktiv ist. Der Server raet anhand des User-Agents
 * (`initialMobile`), damit Smartphones ohne Aufblitzen der Desktop-Ansicht rendern; nach dem
 * Mount entscheidet allein die tatsaechliche Breite (Tablets, schmal gezogene Fenster).
 *
 * Seiten mit getrennter Mobil- und Desktop-Komponente (ResponsiveView) wechseln nicht mitten in
 * einer Eingabe: solange ein Dialog offen ist (`useHoldViewportSwitch`, u. a. in `Modal`) oder der
 * Fokus in einem Eingabefeld der Seite steht, bleibt die bisherige Variante stehen und folgt erst
 * danach. Die Shell schaltet sofort um; der Seiteninhalt bleibt dabei montiert (app-shell.tsx).
 * Die erste Korrektur nach dem Laden (Server-Annahme -> tatsaechliche Breite) wird nie aufgehalten
 * und baut die Shell bewusst neu auf (`epoch`, Key in app-shell.tsx): eingegeben wurde da noch
 * nichts, und neu eingefuegte Knoten zaehlen anders als verschobene nicht als Layout-Shift (CLS).
 */
export function ViewportProvider({ initialMobile, children }: { initialMobile: boolean; children: ReactNode }) {
  const [isMobile, setIsMobile] = useState(initialMobile);
  const [contentMobile, setContentMobile] = useState(initialMobile);
  const holds = useRef(0);
  const initialMobileRef = useRef(initialMobile);
  const [epoch, setEpoch] = useState(0);
  const syncContentRef = useRef<() => void>(() => {});

  useEffect(() => {
    const media = window.matchMedia(MOBILE_MEDIA_QUERY);
    const syncContent = () => {
      if (holds.current > 0 || isEditingPageContent()) return;
      setContentMobile(media.matches);
    };
    syncContentRef.current = syncContent;
    const update = () => {
      setIsMobile(media.matches);
      syncContent();
    };
    setIsMobile(media.matches);
    setContentMobile(media.matches);
    if (media.matches !== initialMobileRef.current) setEpoch(1);
    // Verlaesst der Fokus das Eingabefeld, folgt ein aufgeschobener Wechsel. Erst im naechsten
    // Task pruefen: waehrend focusout steht der Fokus noch nicht auf dem neuen Ziel.
    let timer: number | undefined;
    const onFocusOut = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(syncContent, 0);
    };
    media.addEventListener("change", update);
    document.addEventListener("focusout", onFocusOut);
    return () => {
      window.clearTimeout(timer);
      media.removeEventListener("change", update);
      document.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  const hold = useCallback(() => {
    holds.current += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      holds.current -= 1;
      if (holds.current === 0) syncContentRef.current();
    };
  }, []);

  const value = useMemo(() => ({ isMobile, contentMobile, hold, epoch }), [isMobile, contentMobile, hold, epoch]);
  return <ViewportContext.Provider value={value}>{children}</ViewportContext.Provider>;
}

/** Breite der Shell: Navigation und Rahmen. */
export function useIsMobile(): boolean {
  return useContext(ViewportContext).isMobile;
}

/** Zaehler fuer den Key der Shell: wechselt nur bei der ersten Korrektur nach dem Laden. */
export function useViewportEpoch(): number {
  return useContext(ViewportContext).epoch;
}

/** Breite fuer die Wahl der Seitenvariante (ResponsiveView), mit aufgeschobenem Wechsel. */
export function useContentIsMobile(): boolean {
  return useContext(ViewportContext).contentMobile;
}

/** Haelt den Wechsel der Seitenvariante an, solange `active` gilt (offener Dialog, ungespeicherte Eingabe). */
export function useHoldViewportSwitch(active: boolean): void {
  const { hold } = useContext(ViewportContext);
  useEffect(() => (active ? hold() : undefined), [active, hold]);
}
