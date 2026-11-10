"use client";

import { createContext, ReactNode, useContext, useEffect, useState } from "react";

// Gleicher Umschaltpunkt wie die 900/901-px-Breakpoints in globals.css (design/DESIGN.md
// Abschnitt 2) - bis einschliesslich 900 px gilt die Mobile-Oberflaeche.
export const MOBILE_MEDIA_QUERY = "(max-width: 900px)";

const ViewportContext = createContext(false);

/**
 * Liefert, ob die Mobile-Oberflaeche aktiv ist. Der Server raet anhand des User-Agents
 * (`initialMobile`), damit Smartphones ohne Aufblitzen der Desktop-Ansicht rendern; nach dem
 * Mount entscheidet allein die tatsaechliche Breite (Tablets, schmal gezogene Fenster).
 */
export function ViewportProvider({ initialMobile, children }: { initialMobile: boolean; children: ReactNode }) {
  const [isMobile, setIsMobile] = useState(initialMobile);

  useEffect(() => {
    const media = window.matchMedia(MOBILE_MEDIA_QUERY);
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return <ViewportContext.Provider value={isMobile}>{children}</ViewportContext.Provider>;
}

export function useIsMobile(): boolean {
  return useContext(ViewportContext);
}
