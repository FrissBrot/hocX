"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Refetches the server data when the page is restored via browser back/forward.
 * Without this the browser (bfcache) shows the list exactly as it was left, so
 * anything created in the meantime (e.g. a Word import) is missing until a manual reload.
 */
export function useRefreshOnRestore() {
  const router = useRouter();
  useEffect(() => {
    function onPageShow(event: PageTransitionEvent) {
      if (event.persisted) {
        router.refresh();
      }
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [router]);
}
