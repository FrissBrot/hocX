"use client";

import { ReactNode } from "react";

import { useIsMobile } from "@/lib/hooks/use-is-mobile";

/**
 * Rendert pro Seite genau eine der beiden Oberflaechen. Beide bekommen dieselben, auf dem
 * Server geladenen Daten - die URL bleibt identisch, ein geteilter Link funktioniert auf PC
 * und Handy. Seiten ohne Mobile-Variante nutzen das nicht und zeigen ihre normale Ansicht.
 */
export function ResponsiveView({ mobile, desktop }: { mobile: ReactNode; desktop: ReactNode }) {
  return <>{useIsMobile() ? mobile : desktop}</>;
}
