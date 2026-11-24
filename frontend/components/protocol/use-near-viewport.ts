"use client";

import { RefObject, useEffect, useState } from "react";

/**
 * true, sobald das Element in die Nähe des sichtbaren Bereichs kommt (und danach dauerhaft).
 * Für teure Inhalte im Protokoll, die erst beim Hinscrollen eingehängt werden (L2: Diagramme mit
 * Recharts und Statistik-Abfrage). Ohne IntersectionObserver (alte Browser, Tests) nach dem Einhängen true.
 */
export function useNearViewport(ref: RefObject<HTMLElement | null>, rootMargin = "600px 0px"): boolean {
  // Immer false beginnen (gleich auf Server und Client, sonst Hydration-Fehler)
  const [near, setNear] = useState(false);
  useEffect(() => {
    if (near) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const element = ref.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near, ref, rootMargin]);
  return near;
}
