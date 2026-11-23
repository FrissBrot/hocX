"use client";

import { RefObject, useEffect, useState } from "react";

/**
 * true, sobald das Element in die Nähe des sichtbaren Bereichs kommt (und danach dauerhaft).
 * Für teure Inhalte im Protokoll, die erst beim Hinscrollen eingehängt werden (L2: Diagramme mit
 * Recharts und Statistik-Abfrage). Ohne IntersectionObserver (alte Browser, Tests) sofort true.
 */
export function useNearViewport(ref: RefObject<HTMLElement | null>, rootMargin = "600px 0px"): boolean {
  const [near, setNear] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (near) return;
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
