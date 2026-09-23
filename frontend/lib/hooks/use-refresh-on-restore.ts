"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Lädt Serverdaten auch beim Wiederanzeigen einer im App-Router gespeicherten
 * Seite neu. Dabei werden Effects erneut aktiviert, ohne dass pageshow feuert.
 * pageshow deckt zusätzlich die Wiederherstellung aus dem Browsercache ab.
 */
export function useRefreshOnRestore() {
  const router = useRouter();
  useEffect(() => {
    router.refresh();

    function onPageShow(event: PageTransitionEvent) {
      if (event.persisted) {
        router.refresh();
      }
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [router]);
}
