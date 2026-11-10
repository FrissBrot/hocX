// Bewusst ausserhalb von use-is-mobile.tsx ("use client"): das Root-Layout (Server Component)
// ruft diese Funktion direkt auf.

/** Grobe Server-Schaetzung fuer den ersten Render; der Client korrigiert per matchMedia. */
export function isMobileUserAgent(userAgent: string | null | undefined): boolean {
  return !!userAgent && /Mobi|Android|iPhone|iPod/i.test(userAgent);
}
